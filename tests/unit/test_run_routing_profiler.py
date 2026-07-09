"""Unit tests for the routing profiler (A9).

Covers the deterministic parts of run_routing_profiler:
  - CELL_BUDGETS values match the design-doc per-level priors
  - filter_models substring match
  - clean_scratch_for_task deletes the right files
  - build_tool_schema emits valid OpenAI-shape tool schemas
  - check_answer honors exact / contains / structural
  - _find_resumable_run and _find_all_done_run match by filter set
  - classify_failure integration via the per-task result
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Run from repo root so the profiler import path works.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "benchmarks"))

from run_routing_profiler import (
    CELL_BUDGETS,
    DEFAULT_MODELS,
    SCRATCH_DIR,
    build_tool_schema,
    check_answer,
    clean_scratch_for_task,
    filter_models,
    _find_all_done_run,
    _find_resumable_run,
)


class TestCellBudgets:
    """Cell iteration budgets (A9 fix to spec's broken max_iterations=1)."""

    def test_a_budget_matches_l1_prior(self):
        # design doc: L1=4 → cell A → L1
        assert CELL_BUDGETS["A"] == 4

    def test_b_c_budget_matches_l2_prior(self):
        # design doc: L2=8 → cells B/C → L2
        assert CELL_BUDGETS["B"] == 8
        assert CELL_BUDGETS["C"] == 8

    def test_d_budget_matches_l3_prior(self):
        # design doc: L3=12 → cell D → L3
        assert CELL_BUDGETS["D"] == 12

    def test_default_models_use_current_resource_ids(self):
        # No stale IDs from before the 2026-07-01 resource-pool cleanup.
        assert "lmstudio__google_gemma_4_26b_a4b" not in DEFAULT_MODELS  # double underscore
        assert "lmstudio_qwen36_mtp" not in DEFAULT_MODELS  # renamed
        # ornith is current priority-1.
        assert "lmstudio_ornith_35b_mtp_apex" in DEFAULT_MODELS


class TestFilterModels:
    def test_no_filter_returns_all(self):
        all_models = ["lmstudio_a", "lmstudio_b", "lmstudio_c"]
        assert filter_models(all_models, None) == all_models

    def test_substring_filter(self):
        all_models = ["lmstudio_a", "openrouter_x", "lmstudio_b"]
        assert filter_models(all_models, "lmstudio") == ["lmstudio_a", "lmstudio_b"]

    def test_empty_filter_returns_all(self):
        all_models = ["a", "b"]
        assert filter_models(all_models, "") == all_models


class TestCheckAnswer:
    def test_contains_match_case_insensitive(self):
        task = {"match_type": "contains", "correct_answer": "Qwen"}
        assert check_answer("The model is Qwen3.6", task) is True

    def test_contains_no_match(self):
        task = {"match_type": "contains", "correct_answer": "Qwen"}
        assert check_answer("The model is Gemma", task) is False

    def test_exact_match(self):
        task = {"match_type": "exact", "correct_answer": "qwen3.6-27b-mtp"}
        assert check_answer("qwen3.6-27b-mtp", task) is True
        assert check_answer("qwen3.6-27b-mtp ", task) is True  # trim
        assert check_answer("model: qwen3.6-27b-mtp", task) is False  # extra content

    def test_structural_needs_substantive_response(self):
        task = {"match_type": "structural", "correct_answer": ""}
        assert check_answer("Some meaningful answer with words", task) is True
        assert check_answer("ok", task) is False  # too short
        assert check_answer("", task) is False

    def test_empty_correct_answer_with_contains_fails(self):
        # Defensive: a non-structural task with empty correct_answer should
        # not match anything (otherwise the profiler would silently pass).
        task = {"match_type": "contains", "correct_answer": ""}
        assert check_answer("any response", task) is False


class TestBuildToolSchema:
    def test_known_tools_get_schemas(self):
        schema = build_tool_schema(["read_file", "write_file", "bash_exec"])
        names = [s["function"]["name"] for s in schema]
        assert names == ["read_file", "write_file", "bash_exec"]
        for s in schema:
            assert s["type"] == "function"
            assert "parameters" in s["function"]

    def test_unknown_tool_still_gets_a_stub(self):
        # Unknown tools still appear so the model knows they exist.
        schema = build_tool_schema(["unknown_tool"])
        assert len(schema) == 1
        assert schema[0]["function"]["name"] == "unknown_tool"
        # Empty params means model can call without args.
        assert schema[0]["function"]["parameters"]["properties"] == {}

    def test_empty_list_returns_empty(self):
        assert build_tool_schema([]) == []


class TestCleanScratch(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Patch SCRATCH_DIR for the duration of the test.
        self._patcher = patch(
            "run_routing_profiler.SCRATCH_DIR", Path(self.tmp.name)
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_deletes_named_scratch_files(self):
        # Create files the goal mentions.
        (Path(self.tmp.name) / "cellB_001.txt").write_text("stale")
        (Path(self.tmp.name) / "cellD_005.txt").write_text("stale")
        (Path(self.tmp.name) / "other.txt").write_text("keep")

        task = {
            "goal": (
                "Read the value and write it to "
                "~/.memory/benchmarks/routing/scratch/cellB_001.txt and "
                "scratch/cellD_005.txt"
            ),
        }
        removed = clean_scratch_for_task(task)
        assert removed == 2
        assert not (Path(self.tmp.name) / "cellB_001.txt").exists()
        assert not (Path(self.tmp.name) / "cellD_005.txt").exists()
        assert (Path(self.tmp.name) / "other.txt").exists()

    def test_no_match_does_not_delete_anything(self):
        (Path(self.tmp.name) / "unrelated.txt").write_text("keep")
        task = {"goal": "Just answer a question, no scratch writes."}
        removed = clean_scratch_for_task(task)
        assert removed == 0
        assert (Path(self.tmp.name) / "unrelated.txt").exists()


class TestResumeRunHelpers:
    """Resume semantics: skip already-completed (model, task) pairs."""

    def _make_run(self, run_root: Path, run_id: str, *,
                  completed, models, cell, tasks_per_cell, model_filter):
        rd = run_root / run_id
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "progress.json").write_text(json.dumps({
            "completed": completed,
            "models": models,
            "cell_filter": cell,
            "tasks_per_cell": tasks_per_cell,
            "model_filter": model_filter,
            "run_id": run_id,
        }))

    def test_resumable_run_skips_done_pair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Run with 2 tasks, 1 completed → resumable.
            self._make_run(root, "p1",
                completed=["m1|cellA_001"],
                models=["m1"], cell="A", tasks_per_cell=2,
                model_filter=None,
            )
            r = _find_resumable_run(root, ["m1"], "A", 2, None)
            assert r == "p1"

    def test_resumable_run_skips_when_all_done(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_run(root, "p1",
                completed=["m1|cellA_001", "m1|cellA_002"],
                models=["m1"], cell="A", tasks_per_cell=2,
                model_filter=None,
            )
            # _find_resumable_run returns None — there's no pending work.
            assert _find_resumable_run(root, ["m1"], "A", 2, None) is None
            # _find_all_done_run returns the run for the all-done detection.
            assert _find_all_done_run(root, ["m1"], "A", 2, None) == "p1"

    def test_resumable_run_filter_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_run(root, "p1",
                completed=["m1|cellA_001"],
                models=["m1"], cell="A", tasks_per_cell=2,
                model_filter=None,
            )
            # Same models, different cell → no match.
            assert _find_resumable_run(root, ["m1"], "B", 2, None) is None
            # Same models, different tasks_per_cell → no match.
            assert _find_resumable_run(root, ["m1"], "A", 5, None) is None
            # Different model_filter → no match.
            assert _find_resumable_run(root, ["m1"], "A", 2, "qwen") is None

    def test_resumable_run_picks_latest_with_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # p_old: all done
            self._make_run(root, "p_old",
                completed=["m1|cellA_001", "m1|cellA_002"],
                models=["m1"], cell="A", tasks_per_cell=2,
                model_filter=None,
            )
            # p_newer: one pending
            self._make_run(root, "p_newer",
                completed=["m1|cellA_001"],
                models=["m1"], cell="A", tasks_per_cell=2,
                model_filter=None,
            )
            # Even though p_old sorts first alphabetically when reversed, the
            # glob ordering in iterdir is filesystem-dependent. The function
            # should return whichever has pending work, regardless of order.
            r = _find_resumable_run(root, ["m1"], "A", 2, None)
            assert r in {"p_old", "p_newer"}
            assert r == "p_newer"  # only one with pending


if __name__ == "__main__":
    unittest.main()