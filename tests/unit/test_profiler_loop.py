"""Tests for the A11.2 tool-execution loop in run_task_with_model.

Mocks the LLM call so we can drive specific response shapes:
  - tool_call → execute → tool result → next LLM call
  - final answer (prose) → check_answer → exit
  - tool_call with no follow-up → budget exhausted
  - tool error path → tool result carries the error
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "benchmarks"))

from run_routing_profiler import run_task_with_model  # noqa: E402


def _make_response(content=None, tool_calls=None, finish_reason="stop"):
    """Build a fake OpenAI-shape chat completion response."""
    msg: dict = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    else:
        msg["content"] = None
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "choices": [{"message": msg, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "_selected_model": "test-model",
    }


def _tool_call(call_id, name, arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments) if not isinstance(arguments, str) else arguments,
        },
    }


class TestToolCallLoop(unittest.IsolatedAsyncioTestCase):
    """Drive run_task_with_model through scripted LLM responses."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scratch = Path(self.tmp.name) / "scratch"
        self.scratch.mkdir()

        # Patch SCRATCH_DIR so the executor writes to the test dir, not real scratch.
        patcher = patch("profiler_tool_executor.Path",
                        side_effect=lambda p: Path(self.tmp.name) / p if p == "scratch" else Path(p))
        # The above won't work cleanly because Path is heavily used. Instead
        # patch ProfilerExecutionContext's scratch_dir.
        self._ctx_patcher = patch(
            "profiler_tool_executor.ProfilerExecutionContext.__init__",
            lambda self_, task, **kw: _init_test_ctx(self_, task, self.scratch),
        )
        self._ctx_patcher.start()
        self.addCleanup(self._ctx_patcher.stop)

        # Patch load_resource so we don't need a real resource pool.
        self._resource = {
            "base_url": "http://test", "model": "test-model",
            "api_key": "test", "provider": "openai", "output_limit": 4096,
        }
        self._resource_patcher = patch(
            "run_routing_profiler.load_resource", return_value=self._resource
        )
        self._resource_patcher.start()
        self.addCleanup(self._resource_patcher.stop)

        # Default task — cell B-style read+write with structural verification.
        # Structural match means the model just needs to do the work; check
        # the scratch file separately. (The exact-match tasks like B_001
        # require the model to ALSO restate the value in prose — see
        # test_prose_after_tool_call for that case.)
        self.task = {
            "id": "cellB_002", "cell": "B",
            "goal": "Count files in popo/task_history/ and write count to scratch/cellB_002.txt",
            "correct_answer": "36",
            "match_type": "structural",
            "declared_tools": ["bash_exec", "write_file"],
        }

    def _drive(self, scripted_responses):
        """Patch UnifiedLLMClient.call_async to return scripted responses in order.

        UnifiedLLMClient is imported lazily inside run_task_with_model
        ("from app.llm.unified_client import UnifiedLLMClient"), so we
        patch the import path, not the profiler module's namespace.
        """
        iter_responses = iter(scripted_responses)
        async def fake_call_async(messages, resource_config, model_override=None, tools=None):
            try:
                return next(iter_responses)
            except StopIteration:
                return _make_response(content="(out of script)")
        patcher = patch(
            "app.llm.unified_client.UnifiedLLMClient.call_async",
            new=AsyncMock(side_effect=fake_call_async),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake_call_async

    async def test_tool_call_then_final_answer_passes(self):
        # First call: model calls bash_exec to count files.
        # Second call: model calls write_file with the count.
        # Third call: model gives a substantive final answer (structural).
        responses = [
            _make_response(tool_calls=[
                _tool_call("c1", "bash_exec", {"command": "ls -1 | wc -l"})
            ]),
            _make_response(tool_calls=[
                _tool_call("c2", "write_file",
                           {"path": str(self.scratch / "cellB_002.txt"),
                            "content": "36"})
            ]),
            _make_response(content="I counted 36 files and wrote the result to scratch."),
        ]
        self._drive(responses)
        result = await run_task_with_model(self.task, "test_resource", budget=8, max_duration_s=60)

        self.assertTrue(result["success"], result)
        self.assertEqual(result["iterations"], 3)
        self.assertEqual(result["tool_call_count"], 2)
        self.assertEqual(result["tool_error_count"], 0)
        # The scratch file should exist with the right content.
        out_file = self.scratch / "cellB_002.txt"
        self.assertTrue(out_file.exists())
        self.assertEqual(out_file.read_text(), "36")
        self.assertEqual(result["failure_class"], None)  # clean pass

    async def test_tool_call_but_no_final_answer_exhausts_budget(self):
        # Model keeps calling tools until budget runs out.
        responses = [
            _make_response(tool_calls=[_tool_call(f"c{i}", "bash_exec", {"command": "echo x"})])
            for i in range(4)  # budget is 4
        ]
        self._drive(responses)
        result = await run_task_with_model(self.task, "test_resource", budget=4, max_duration_s=60)

        self.assertFalse(result["success"])
        self.assertEqual(result["iterations"], 4)
        self.assertEqual(result["tool_call_count"], 4)
        # No final answer means check_answer never had anything to verify
        # against; failure_class is determined by elapsed_s. If the run was
        # fast (sub-30s), it'll be verification_mismatch. If over 30s,
        # final_answer_slow. If over 120s, timeout.
        self.assertIn(result["failure_class"],
                      {"verification_mismatch", "final_answer_slow", "timeout"})

    async def test_tool_error_recorded_but_loop_continues(self):
        # First call: bash_exec with cd .. → tool returns error.
        # Second call: bash_exec with a valid command → succeeds.
        # Third call: write_file with the right path → succeeds.
        # Fourth call: prose answer.
        responses = [
            _make_response(tool_calls=[
                _tool_call("c1", "bash_exec", {"command": "cd .. && ls"})
            ]),
            _make_response(tool_calls=[
                _tool_call("c2", "bash_exec", {"command": "ls -1 | wc -l"})
            ]),
            _make_response(tool_calls=[
                _tool_call("c3", "write_file",
                           {"path": str(self.scratch / "cellB_002.txt"),
                            "content": "36"})
            ]),
            _make_response(content="Wrote the count to scratch."),
        ]
        self._drive(responses)
        result = await run_task_with_model(self.task, "test_resource", budget=8, max_duration_s=60)

        self.assertTrue(result["success"], result)
        self.assertEqual(result["tool_call_count"], 3)
        self.assertEqual(result["tool_error_count"], 1)  # cd .. denied
        # The error was visible to the model — it should have continued.
        first_log = result["tool_calls_log"][0]
        self.assertFalse(first_log["ok"])
        self.assertIn("cd above scratch", first_log["error"])

    async def test_prose_only_no_tool_calls_uses_legacy_feedback_path(self):
        # No tool calls in any response. The task is match_type=contains
        # so a wrong-prose answer fails verification; the loop should
        # feed back hints and eventually fail.
        task = {
            "id": "cellB_004", "cell": "B",
            "goal": "Find the highest-priority resource and tell me its model name.",
            "correct_answer": "qwen3.6-35b-a3b-mtp",
            "match_type": "contains",
            "declared_tools": ["read_file", "write_file"],  # schema sent but not used
        }
        responses = [
            _make_response(content="I don't know"),
            _make_response(content="Still don't know"),
        ]
        self._drive(responses)
        result = await run_task_with_model(task, "test_resource", budget=2, max_duration_s=60)

        self.assertFalse(result["success"])
        self.assertEqual(result["iterations"], 2)
        self.assertEqual(result["tool_call_count"], 0)
        self.assertEqual(result["failure_class"], "verification_mismatch")

    async def test_no_declared_tools_skips_executor_entirely(self):
        # Cell A task: no declared_tools, so the tool schema isn't sent
        # and the loop just runs the A9-style retry-with-feedback shape.
        task = {
            "id": "cellA_001", "cell": "A",
            "goal": "What is the answer?",
            "correct_answer": "42",
            "match_type": "contains",
            "declared_tools": [],  # no tools
        }
        responses = [_make_response(content="42")]
        self._drive(responses)
        result = await run_task_with_model(task, "test_resource", budget=4, max_duration_s=60)

        self.assertTrue(result["success"])
        self.assertEqual(result["iterations"], 1)
        self.assertEqual(result["tool_call_count"], 0)


def _init_test_ctx(ctx, task, scratch_dir):
    """Replacement __init__ for the test — pins scratch to a temp dir
    and uses minimal allowed_roots (so the deny tests can target /etc
    paths and get the expected denial)."""
    ctx.task = task
    ctx.scratch_dir = scratch_dir
    ctx.scratch_dir.mkdir(parents=True, exist_ok=True)
    ctx.allowed_roots = [scratch_dir.parent]  # the tmp dir is the only readable root
    ctx.call_log = []


if __name__ == "__main__":
    unittest.main()