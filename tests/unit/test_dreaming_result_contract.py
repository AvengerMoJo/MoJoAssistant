"""Dreaming must fail honestly instead of reporting success for a night that consolidated nothing.

2026-10-08 (F3): global dreaming 'completed' for a week while the newest archive was 8 days old.
Mechanisms found: ResourcePoolLLMInterface.generate_response swallowed LLM failures and returned "";
the pipeline turned an empty answer into zero chunks and still reported success; and the nightly job
re-dreamed the same last 200 messages every night (no watermark).
"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.llm.resource_pool_interface import DreamingLLMError, ResourcePoolLLMInterface
from app.scheduler.handlers.dreaming import DreamingHandler
from app.scheduler.models import Task, TaskType


class TestLLMInterfaceRaises(unittest.TestCase):
    def _iface(self, resource):
        rm = MagicMock()
        rm.acquire.return_value = resource
        return ResourcePoolLLMInterface(rm), rm

    def _resource(self):
        r = MagicMock()
        r.id, r.base_url, r.model, r.api_key, r.output_limit, r.provider = "r1", "http://x/v1", "m", "k", 4096, "openai"
        return r

    def test_no_resource_raises(self):
        iface, _ = self._iface(None)
        with self.assertRaises(DreamingLLMError) as cm:
            iface.generate_response("hi")
        self.assertIn("no LLM resource", str(cm.exception))

    def test_connection_failure_raises_and_is_recorded(self):
        iface, rm = self._iface(self._resource())
        with patch("app.llm.unified_client.UnifiedLLMClient.call_async", side_effect=ConnectionError("refused")):
            with self.assertRaises(DreamingLLMError):
                iface.generate_response("hi")
        rm.record_usage.assert_called_with("r1", success=False, error_message="refused")

    def test_empty_completion_raises(self):
        iface, _ = self._iface(self._resource())
        async def empty(*a, **k):
            return {"choices": [{"message": {"content": "   "}}]}
        with patch("app.llm.unified_client.UnifiedLLMClient.call_async", side_effect=empty):
            with self.assertRaises(DreamingLLMError) as cm:
                iface.generate_response("hi")
        self.assertIn("empty completion", str(cm.exception))

    def test_good_completion_is_returned(self):
        iface, _ = self._iface(self._resource())
        async def ok(*a, **k):
            return {"choices": [{"message": {"content": '{"chunks": []}'}}]}
        with patch("app.llm.unified_client.UnifiedLLMClient.call_async", side_effect=ok):
            self.assertEqual(iface.generate_response("hi"), '{"chunks": []}')


class _Pipeline:
    storage = None

    def __init__(self, chunks, clusters):
        self.chunks, self.clusters = chunks, clusters

    async def process_conversation(self, conversation_id, conversation_text, metadata):
        return {"status": "success", "stages": {"D_archive": {"path": "x"}, "B_chunks": {"count": self.chunks},
                                                "C_clusters": {"count": self.clusters}}}


def _run(chunks, clusters, text, **cfg):
    ctx = MagicMock()
    ctx._memory_service = None
    ctx.get_dreaming_pipeline.return_value = _Pipeline(chunks, clusters)
    task = Task(id="t", type=TaskType.DREAMING,
                config={"conversation_id": "c", "conversation_text": text, "enforce_off_peak": False, **cfg})
    return asyncio.run(DreamingHandler().execute(task, ctx))


class TestResultContract(unittest.TestCase):
    LONG = "word " * 200   # 1000 chars

    def test_real_input_with_no_chunks_is_a_failure(self):
        r = _run(0, 0, self.LONG)
        self.assertFalse(r.success)
        self.assertIn("0 chunks and 0 clusters", r.error_message)

    def test_chunks_but_no_clusters_is_a_failure(self):
        self.assertFalse(_run(3, 0, self.LONG).success)

    def test_real_output_succeeds(self):
        r = _run(3, 2, self.LONG)
        self.assertTrue(r.success)
        self.assertEqual(r.metrics["c_clusters_count"], 2)

    def test_tiny_input_may_legitimately_produce_nothing(self):
        self.assertTrue(_run(0, 0, "hi there").success)


class TestWatermark(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.store = self.dir / "conv.json"
        self.wm = self.dir / "state" / "wm.json"
        p = patch.object(DreamingHandler, "_global_watermark_path", staticmethod(lambda: self.wm))
        p.start()
        self.addCleanup(p.stop)

    def _write(self, n, start=0):
        msgs = [{"message_type": "user", "text_content": f"message {i}", "created_at": f"2026-10-08T10:{i:02d}:00"}
                for i in range(start, start + n)]
        self.store.write_text(json.dumps(msgs), encoding="utf-8")

    def _build(self, **cfg):
        return DreamingHandler._build_automatic_dreaming_input({"conversation_store_path": str(self.store), **cfg})

    def test_first_run_takes_the_latest_n(self):
        self._write(10)
        r = self._build(lookback_messages=4)
        self.assertEqual(r["metadata"]["message_count"], 4)
        self.assertIn("message 9", r["conversation_text"])
        self.assertNotIn("message 5", r["conversation_text"])
        self.assertEqual(r["metadata"]["watermark_candidate"], "2026-10-08T10:09:00")

    def test_after_commit_only_newer_messages_are_dreamed_and_nothing_new_is_none(self):
        self._write(10)
        DreamingHandler._commit_global_watermark("2026-10-08T10:09:00")
        self.assertIsNone(self._build())                       # nothing new
        self._write(13)
        r = self._build()
        self.assertEqual(r["metadata"]["message_count"], 3)
        self.assertIn("message 10", r["conversation_text"])
        self.assertNotIn("message 9", r["conversation_text"])

    def test_backlog_is_worked_off_oldest_first(self):
        self._write(30)
        DreamingHandler._commit_global_watermark("2026-10-08T10:09:00")
        r = self._build(lookback_messages=5)
        self.assertIn("message 10", r["conversation_text"])
        self.assertIn("message 14", r["conversation_text"])
        self.assertNotIn("message 15", r["conversation_text"])
        self.assertEqual(r["metadata"]["watermark_candidate"], "2026-10-08T10:14:00")

    def test_successful_run_advances_the_watermark_but_a_contract_failure_does_not(self):
        self._write(10)
        text = "x" * 1000
        ctx = MagicMock(); ctx._memory_service = None
        task = Task(id="t", type=TaskType.DREAMING, config={"automatic": True, "enforce_off_peak": False,
                                                            "conversation_store_path": str(self.store)})
        with patch.object(DreamingHandler, "_build_automatic_dreaming_input",
                          return_value={"conversation_id": "a", "conversation_text": text,
                                        "metadata": {"watermark_candidate": "2026-10-08T10:09:00"}}):
            ctx.get_dreaming_pipeline.return_value = _Pipeline(0, 0)
            self.assertFalse(asyncio.run(DreamingHandler().execute(task, ctx)).success)
            self.assertFalse(self.wm.exists())                 # failed run -> not advanced
            ctx.get_dreaming_pipeline.return_value = _Pipeline(2, 2)
            self.assertTrue(asyncio.run(DreamingHandler().execute(task, ctx)).success)
            self.assertEqual(json.loads(self.wm.read_text())["created_at"], "2026-10-08T10:09:00")


if __name__ == "__main__":
    unittest.main()


class TestConfigurableTimeout(unittest.TestCase):
    def test_configured_timeout_reaches_the_client_and_a_timeout_surfaces_as_an_error(self):
        rm = MagicMock()
        r = MagicMock()
        r.id, r.base_url, r.model, r.api_key, r.output_limit, r.provider = "r1", "http://x/v1", "m", "k", 4096, "openai"
        rm.acquire.return_value = r
        iface = ResourcePoolLLMInterface(rm, timeout_seconds=900)
        seen = {}

        async def capture(self_, messages, resource_config, model_override=None, tools=None):
            seen.update(resource_config)
            raise TimeoutError()
        with patch("app.llm.unified_client.UnifiedLLMClient.call_async", capture):
            with self.assertRaises(DreamingLLMError) as cm:
                iface.generate_response("hi")
        self.assertEqual(seen["timeout"], 900)
        self.assertIn("TimeoutError", str(cm.exception))

    def test_default_is_ten_minutes_not_two(self):
        self.assertEqual(ResourcePoolLLMInterface(MagicMock())._timeout, 600.0)

    def test_timeout_errors_are_classified_as_timeouts(self):
        from app.scheduler.run_ledger import classify_error
        self.assertEqual(classify_error("LLM call failed after waiting up to 120s: TimeoutError: "), "timeout")


class TestInputBudget(TestWatermark):
    """The nightly window is bounded by size: 200 messages were 288,072 chars in one prompt and every
    run produced 0 chunks (2026-10-09)."""

    def _write_sized(self, n, size, start=0):
        msgs = [{"message_type": "user", "text_content": f"m{i} " + "x" * size, "created_at": f"2026-10-08T10:{i:02d}:00"}
                for i in range(start, start + n)]
        self.store.write_text(json.dumps(msgs), encoding="utf-8")

    def test_first_run_takes_the_newest_messages_that_fit_in_chronological_order(self):
        self._write_sized(30, 1000)
        r = self._build(max_input_chars=5000)
        self.assertLessEqual(len(r["conversation_text"]), 5000)
        self.assertIn("m29 ", r["conversation_text"])                       # newest included
        self.assertNotIn("m0 ", r["conversation_text"])
        text = r["conversation_text"]
        self.assertLess(text.index("m26 "), text.index("m29 "))             # still oldest -> newest
        self.assertEqual(r["metadata"]["watermark_candidate"], "2026-10-08T10:29:00")

    def test_backlog_window_is_oldest_first_and_watermark_stops_at_the_last_included(self):
        self._write_sized(30, 1000)
        DreamingHandler._commit_global_watermark("2026-10-08T10:09:00")
        r = self._build(max_input_chars=5000)
        self.assertIn("m10 ", r["conversation_text"])
        self.assertNotIn("m29 ", r["conversation_text"])
        n = r["metadata"]["message_count"]
        self.assertEqual(r["metadata"]["watermark_candidate"], f"2026-10-08T10:{9 + n:02d}:00")

    def test_one_oversized_message_is_truncated_but_never_blocks_the_run(self):
        self._write_sized(1, 50_000)
        r = self._build(max_input_chars=2000, max_message_chars=1500)
        self.assertEqual(r["metadata"]["message_count"], 1)
        self.assertIn("…[truncated]", r["conversation_text"])
        self.assertLess(len(r["conversation_text"]), 1700)

    def test_default_budget_keeps_a_busy_store_under_the_limit(self):
        self._write_sized(200, 1400)
        r = self._build()
        self.assertLessEqual(len(r["conversation_text"]), 24000)
        self.assertGreater(r["metadata"]["message_count"], 10)


class TestReasoningModelBudget(unittest.TestCase):
    """2026-10-09: a thinking model spent all 4096 output tokens on reasoning and returned content ''.
    The error must say so, and the default budget must leave room for an answer."""

    def _iface(self, **kw):
        rm = MagicMock()
        r = MagicMock()
        r.id, r.base_url, r.model, r.api_key, r.output_limit, r.provider = "ornith", "http://x/v1", "m", "k", 32000, "openai"
        rm.acquire.return_value = r
        return ResourcePoolLLMInterface(rm, **kw)

    def test_empty_content_with_length_finish_explains_the_reasoning_budget(self):
        async def reasoning_only(*a, **k):
            return {"choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                    "usage": {"completion_tokens": 4096, "completion_tokens_details": {"reasoning_tokens": 4096}}}
        with patch("app.llm.unified_client.UnifiedLLMClient.call_async", side_effect=reasoning_only):
            with self.assertRaises(DreamingLLMError) as cm:
                self._iface(max_tokens=4096).generate_response("hi")
        msg = str(cm.exception)
        self.assertIn("4096 spent on reasoning", msg)
        self.assertIn("4096-token output budget", msg)
        self.assertIn("dreaming.max_output_tokens", msg)

    def test_default_output_budget_is_16000_capped_by_the_resource(self):
        seen = {}

        async def ok(self_, messages, resource_config, model_override=None, tools=None):
            seen.update(resource_config)
            return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        with patch("app.llm.unified_client.UnifiedLLMClient.call_async", ok):
            self._iface().generate_response("hi")
        self.assertEqual(seen["output_limit"], 16000)
        small = self._iface()
        small._rm.acquire.return_value.output_limit = 8192
        with patch("app.llm.unified_client.UnifiedLLMClient.call_async", ok):
            small.generate_response("hi")
        self.assertEqual(seen["output_limit"], 8192)
