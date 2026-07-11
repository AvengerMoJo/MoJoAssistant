"""Tests for ExecutionRecord + BenchmarkStore.record_execution.

Specifically the W2.1 changes that add cell/level fields populated
from the router's decision in cfg["_routing"].
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

# Repo root on path
import sys
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from app.scheduler.benchmark_store import (  # noqa: E402
    BenchmarkStore, ExecutionRecord,
)


class TestExecutionRecordSchema(unittest.TestCase):
    """The W2.1 schema additions: cell + level on every record."""

    def test_default_cell_and_level_are_none(self):
        # Backwards compat: existing callers that don't pass
        # cell/level still construct valid records.
        rec = ExecutionRecord(
            ts="2026-07-11T00:00:00", task_id="t1",
            goal_hash="abc", goal_preview="do thing",
            role_id=None, resource_id="m1", model="m1",
            success=True, iterations=1, duration_s=1.0,
            final_answer_len=0, final_answer_hash="",
        )
        self.assertIsNone(rec.cell)
        self.assertIsNone(rec.level)

    def test_cell_and_level_round_trip_through_to_from_dict(self):
        rec = ExecutionRecord(
            ts="2026-07-11T00:00:00", task_id="t1",
            goal_hash="abc", goal_preview="do thing",
            role_id=None, resource_id="m1", model="m1",
            success=True, iterations=1, duration_s=1.0,
            final_answer_len=0, final_answer_hash="",
            cell="B", level="L2_multi_step",
        )
        d = rec.to_dict()
        self.assertEqual(d["cell"], "B")
        self.assertEqual(d["level"], "L2_multi_step")
        restored = ExecutionRecord.from_dict(d)
        self.assertEqual(restored.cell, "B")
        self.assertEqual(restored.level, "L2_multi_step")

    def test_legacy_record_without_cell_loads_with_none(self):
        # A pre-W2.1 line in execution_log.jsonl has no cell/level.
        # from_dict must load it cleanly (None defaults).
        legacy_line = {
            "ts": "2026-07-10T00:00:00", "task_id": "t1",
            "goal_hash": "abc", "goal_preview": "do thing",
            "role_id": None, "resource_id": "m1", "model": "m1",
            "success": True, "iterations": 1, "duration_s": 1.0,
            "final_answer_len": 0, "final_answer_hash": "",
            "is_rerun": False,
        }
        rec = ExecutionRecord.from_dict(legacy_line)
        self.assertIsNone(rec.cell)
        self.assertIsNone(rec.level)
        # The rest still loads.
        self.assertEqual(rec.resource_id, "m1")
        self.assertTrue(rec.success)


class TestRecordExecutionPopulatesCellAndLevel(unittest.TestCase):
    """The handler writes cfg['_routing'] = {cell, level, ...};
    record_execution must read it."""

    def setUp(self):
        super().setUp()
        # Use a temp dir so we don't pollute the real execution log.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Patch the module-level path constants.
        import app.scheduler.benchmark_store as bs
        self._log_patcher = unittest.mock.patch.object(
            bs, "_log_path",
            lambda: Path(self.tmp.name) / "execution_log.jsonl",
        )
        self._report_patcher = unittest.mock.patch.object(
            bs, "_report_path",
            lambda: Path(self.tmp.name) / "report.json",
        )
        self._log_patcher.start()
        self._report_patcher.start()
        self.addCleanup(self._log_patcher.stop)
        self.addCleanup(self._report_patcher.stop)
        self.store = BenchmarkStore()

    def _make_task(self, *, routing=None, **config_overrides):
        """Build a minimal Task-like object for record_execution."""
        from types import SimpleNamespace
        config = {"goal": "do thing"}
        if routing is not None:
            config["_routing"] = routing
        config.update(config_overrides)
        return SimpleNamespace(id="task-1", config=config)

    def _make_result(self, *, success=True, resource="m1", model="m1",
                     iterations=1, duration=1.0, final_answer="ok"):
        from types import SimpleNamespace
        return SimpleNamespace(
            success=success,
            metrics={"final_answer": final_answer},
            resource_id=resource,
            model=model,
            iterations=iterations,
            duration_s=duration,
        )

    def test_routing_cell_and_level_land_in_record(self):
        task = self._make_task(routing={
            "cell": "B", "level": "L2_multi_step",
            "model_id": "m1", "confidence": 0.85,
        })
        self.store.record_execution(task, self._make_result(success=True))
        rec = self._read_last_record()
        self.assertEqual(rec.cell, "B")
        self.assertEqual(rec.level, "L2_multi_step")

    def test_no_routing_in_config_leaves_cell_and_level_none(self):
        # Pre-routing tasks / coding_agent overrides / etc. — no
        # _routing in config. cell/level default to None; the
        # record is still written.
        task = self._make_task()  # no _routing
        self.store.record_execution(task, self._make_result(success=True))
        rec = self._read_last_record()
        self.assertIsNone(rec.cell)
        self.assertIsNone(rec.level)

    def test_empty_routing_dict_leaves_cell_and_level_none(self):
        # Defensive: handler might have set cfg["_routing"] = {} on
        # some failure paths. Don't crash; record with None.
        task = self._make_task(routing={})
        self.store.record_execution(task, self._make_result(success=False))
        rec = self._read_last_record()
        self.assertIsNone(rec.cell)
        self.assertIsNone(rec.level)

    def test_routing_with_only_cell_no_level(self):
        # The handler always populates both, but if a future caller
        # only knows the cell, we shouldn't crash.
        task = self._make_task(routing={"cell": "C"})
        self.store.record_execution(task, self._make_result(success=True))
        rec = self._read_last_record()
        self.assertEqual(rec.cell, "C")
        self.assertIsNone(rec.level)

    def test_routing_with_only_level_no_cell(self):
        task = self._make_task(routing={"level": "L4_orchestration"})
        self.store.record_execution(task, self._make_result(success=True))
        rec = self._read_last_record()
        self.assertEqual(rec.level, "L4_orchestration")
        self.assertIsNone(rec.cell)

    def test_record_execution_does_not_crash_on_routing_failure(self):
        # Defensive: if reading _routing raises, the rest of the
        # record should still be written. (Robustness matters —
        # BenchmarkStore is called from the scheduler's hot path.)
        task = self._make_task(routing="not a dict")  # malformed
        self.store.record_execution(task, self._make_result(success=True))
        rec = self._read_last_record()
        self.assertTrue(rec.success)
        # cell/level are None because the routing was malformed —
        # that's the right defensive behavior.
        self.assertIsNone(rec.cell)
        self.assertIsNone(rec.level)

    # ---- helpers ----

    def _read_last_record(self):
        import app.scheduler.benchmark_store as bs
        with bs._log_path().open() as f:
            lines = [ln for ln in f if ln.strip()]
        self.assertGreater(len(lines), 0, "no records written")
        return ExecutionRecord.from_dict(json.loads(lines[-1]))


if __name__ == "__main__":
    unittest.main()