"""
Unit tests for the Bonsai Growth Architecture.

Covers:
  - GrowthSnapshot  (creation, serialization)
  - SnapshotManager (save, load, pin, versioning)
  - BonsaiEngine    (growth reports, dimension drift, validation)
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scheduler.bonsai import BonsaiEngine, GrowthSnapshot, SnapshotManager


class TestGrowthSnapshot(unittest.TestCase):

    def test_creates_snapshot(self):
        dims = {
            "core_values": {"score": 90, "summary": "Evidence-based"},
            "cognitive_style": {"score": 85, "summary": "Systematic"},
        }
        snap = GrowthSnapshot(
            role_id="test_role",
            version=1,
            dimensions=dims,
            system_prompt="You are a test assistant.",
            presentation_patterns={"financial": "growth-first"},
            communication_style=["direct", "concise"],
            trigger="test",
        )
        self.assertEqual(snap.role_id, "test_role")
        self.assertEqual(snap.version, 1)
        self.assertEqual(snap.dimensions["core_values"]["score"], 90)
        self.assertIn("direct", snap.communication_style)

    def test_serializes_to_dict(self):
        snap = GrowthSnapshot(
            role_id="test", version=1,
            dimensions={"core_values": {"score": 80}},
            system_prompt="test prompt",
        )
        d = snap.to_dict()
        self.assertEqual(d["version"], 1)
        self.assertEqual(d["role_id"], "test")
        self.assertIn("system_prompt_hash", d)
        self.assertIn("created_at", d)

    def test_from_dict(self):
        data = {
            "version": 2,
            "role_id": "researcher",
            "dimensions": {"core_values": {"score": 95}},
            "trigger": "dreaming",
        }
        snap = GrowthSnapshot.from_dict(data, system_prompt="test")
        self.assertEqual(snap.version, 2)
        self.assertEqual(snap.role_id, "researcher")


class TestSnapshotManager(unittest.TestCase):

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        self._patcher = patch(
            "app.scheduler.bonsai.get_memory_subpath",
            return_value=self._tmp_dir,
        )
        self._patcher.start()
        self.manager = SnapshotManager("test_role")

    def tearDown(self):
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_save_and_load_snapshot(self):
        snap = GrowthSnapshot(
            role_id="test_role", version=1,
            dimensions={"core_values": {"score": 80}},
            system_prompt="test",
        )
        self.manager.save_snapshot(snap)
        self.manager.pin_snapshot(1)

        current = self.manager.get_current()
        self.assertIsNotNone(current)
        self.assertEqual(current.version, 1)

    def test_version_increments(self):
        for i in range(1, 4):
            snap = GrowthSnapshot(
                role_id="test_role", version=i,
                dimensions={"core_values": {"score": 80 + i}},
                system_prompt=f"v{i}",
            )
            self.manager.save_snapshot(snap)

        self.assertEqual(self.manager.get_latest_version(), 3)

    def test_pin_snapshot(self):
        snap = GrowthSnapshot(
            role_id="test_role", version=1,
            dimensions={"core_values": {"score": 80}},
            system_prompt="test",
        )
        self.manager.save_snapshot(snap)
        self.manager.pin_snapshot(1)

        pinned = self.manager.get_pinned()
        self.assertIsNotNone(pinned)
        self.assertEqual(pinned.version, 1)

    def test_list_snapshots(self):
        for i in range(1, 4):
            snap = GrowthSnapshot(
                role_id="test_role", version=i,
                dimensions={},
                system_prompt=f"v{i}",
            )
            self.manager.save_snapshot(snap)

        snapshots = self.manager.list_snapshots()
        self.assertEqual(len(snapshots), 3)

    def test_returns_none_when_no_snapshot(self):
        self.assertIsNone(self.manager.get_current())
        self.assertIsNone(self.manager.get_pinned())

    def test_get_snapshot_by_version(self):
        snap = GrowthSnapshot(
            role_id="test_role", version=2,
            dimensions={"core_values": {"score": 82}},
            system_prompt="test",
        )
        self.manager.save_snapshot(snap)

        loaded = self.manager.get_snapshot(2)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.version, 2)
        self.assertIsNone(self.manager.get_snapshot(99))

    def test_activate_snapshot_switches_current(self):
        for i in (1, 2):
            snap = GrowthSnapshot(
                role_id="test_role", version=i,
                dimensions={"core_values": {"score": 70 + i}},
                system_prompt=f"v{i}",
            )
            self.manager.save_snapshot(snap)

        self.assertTrue(self.manager.activate_snapshot(1))
        current = self.manager.get_current()
        self.assertIsNotNone(current)
        self.assertEqual(current.version, 1)

    def test_activate_snapshot_can_pin(self):
        for i in (1, 2):
            snap = GrowthSnapshot(
                role_id="test_role", version=i,
                dimensions={"core_values": {"score": 80 + i}},
                system_prompt=f"v{i}",
            )
            self.manager.save_snapshot(snap)

        self.assertTrue(self.manager.activate_snapshot(1, pin=True))
        pinned = self.manager.get_pinned()
        self.assertIsNotNone(pinned)
        self.assertEqual(pinned.version, 1)


class TestBonsaiEngine(unittest.TestCase):

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        self._patcher = patch(
            "app.scheduler.bonsai.get_memory_subpath",
            return_value=self._tmp_dir,
        )
        self._patcher.start()
        self.engine = BonsaiEngine("test_role")

    def tearDown(self):
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_generate_growth_report_initial(self):
        dims = {"core_values": {"score": 80, "summary": "Good"}}
        report = self.engine.generate_growth_report(
            old_snapshot=None,
            new_dimensions=dims,
        )
        self.assertIn("Initial State", report)
        self.assertIn("test_role", report)

    def test_generate_growth_report_with_changes(self):
        old_snap = GrowthSnapshot(
            role_id="test_role", version=1,
            dimensions={"core_values": {"score": 75, "summary": "Average"}},
            system_prompt="old",
        )
        new_dims = {"core_values": {"score": 85, "summary": "Improved"}}
        report = self.engine.generate_growth_report(
            old_snapshot=old_snap,
            new_dimensions=new_dims,
            signals=["Owner calibration: more evidence rigor"],
        )
        self.assertIn("Before", report)
        self.assertIn("After", report)
        self.assertIn("75 → 85", report)
        self.assertIn("Action Required", report)

    def test_compute_dimension_drift(self):
        current = {
            "core_values": {"score": 75},
            "cognitive_style": {"score": 80},
        }
        signals = [
            {"dimension": "core_values", "direction": "up", "strength": 0.5, "reason": "test"},
        ]
        new_dims = self.engine.compute_dimension_drift(current, signals, max_drift=5)
        self.assertGreater(new_dims["core_values"]["score"], 75)
        self.assertEqual(new_dims["cognitive_style"]["score"], 80)

    def test_compute_dimension_drift_clamps(self):
        current = {"core_values": {"score": 98}}
        signals = [
            {"dimension": "core_values", "direction": "up", "strength": 1.0},
        ]
        new_dims = self.engine.compute_dimension_drift(current, signals, max_drift=5)
        self.assertEqual(new_dims["core_values"]["score"], 100)

    def test_validate_growth_ok(self):
        old = {"core_values": {"score": 80}}
        new = {"core_values": {"score": 85}}
        result = self.engine.validate_growth(old, new)
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["issues"]), 0)

    def test_validate_growth_contradiction(self):
        old = {"core_values": {"score": 80}, "cognitive_style": {"score": 80}}
        new = {"core_values": {"score": 95}, "cognitive_style": {"score": 50}}
        result = self.engine.validate_growth(old, new)
        self.assertFalse(result["valid"])
        self.assertGreater(len(result["issues"]), 0)

    def test_validate_growth_large_shift_warning(self):
        old = {"core_values": {"score": 50}}
        new = {"core_values": {"score": 80}}
        result = self.engine.validate_growth(old, new)
        self.assertTrue(result["valid"])  # Not invalid, just warned
        self.assertGreater(len(result["warnings"]), 0)

    def test_create_snapshot(self):
        dims = {"core_values": {"score": 85, "summary": "Good"}}
        snap = self.engine.create_snapshot(
            dimensions=dims,
            system_prompt="test prompt",
            trigger="test",
        )
        self.assertEqual(snap.version, 1)
        self.assertEqual(snap.role_id, "test_role")


class TestSystemPromptRoundtrip(unittest.TestCase):
    """Bug 1 — system_prompt must survive save/load/pin cycles."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        self._patcher = patch(
            "app.scheduler.bonsai.get_memory_subpath",
            return_value=self._tmp_dir,
        )
        self._patcher.start()
        self.manager = SnapshotManager("test_role")

    def tearDown(self):
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_system_prompt_stored_in_dict(self):
        snap = GrowthSnapshot(
            role_id="test_role", version=1,
            dimensions={"core_values": {"score": 80}},
            system_prompt="You are a specialized assistant.",
        )
        d = snap.to_dict()
        self.assertIn("system_prompt", d)
        self.assertEqual(d["system_prompt"], "You are a specialized assistant.")

    def test_system_prompt_restored_from_dict(self):
        snap = GrowthSnapshot(
            role_id="test_role", version=1,
            dimensions={},
            system_prompt="Restored prompt here.",
        )
        d = snap.to_dict()
        restored = GrowthSnapshot.from_dict(d)
        self.assertEqual(restored.system_prompt, "Restored prompt here.")

    def test_from_dict_caller_arg_overrides_stored(self):
        snap = GrowthSnapshot(role_id="test_role", version=1, dimensions={}, system_prompt="original")
        d = snap.to_dict()
        restored = GrowthSnapshot.from_dict(d, system_prompt="override")
        self.assertEqual(restored.system_prompt, "override")

    def test_system_prompt_survives_save_load_cycle(self):
        snap = GrowthSnapshot(
            role_id="test_role", version=1,
            dimensions={"core_values": {"score": 75}},
            system_prompt="Persistent prompt across cycles.",
        )
        self.manager.save_snapshot(snap)
        self.manager.pin_snapshot(1)
        loaded = self.manager.get_pinned()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.system_prompt, "Persistent prompt across cycles.")

    def test_system_prompt_survives_pin_and_get_current(self):
        snap = GrowthSnapshot(role_id="test_role", version=1, dimensions={}, system_prompt="live prompt")
        self.manager.save_snapshot(snap)
        self.manager.pin_snapshot(1)
        current = self.manager.get_current()
        self.assertEqual(current.system_prompt, "live prompt")


class TestApprovalMetadata(unittest.TestCase):
    """Bug 2 — pin_snapshot must write approved_by/approved_at into the JSON."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        self._patcher = patch(
            "app.scheduler.bonsai.get_memory_subpath",
            return_value=self._tmp_dir,
        )
        self._patcher.start()
        self.manager = SnapshotManager("test_role")

    def tearDown(self):
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _save(self, version=1):
        snap = GrowthSnapshot(
            role_id="test_role", version=version,
            dimensions={"core_values": {"score": 80}},
            system_prompt="test",
        )
        self.manager.save_snapshot(snap)

    def test_pin_writes_approved_by_to_json(self):
        self._save()
        self.manager.pin_snapshot(1, approved_by="owner")
        path = self.manager._snapshot_path(1)
        data = json.loads(path.read_text())
        self.assertEqual(data["approved_by"], "owner")
        self.assertIsNotNone(data.get("approved_at"))

    def test_pin_default_approved_by_is_owner(self):
        self._save()
        self.manager.pin_snapshot(1)
        data = json.loads(self.manager._snapshot_path(1).read_text())
        self.assertEqual(data["approved_by"], "owner")

    def test_approved_by_readable_via_get_pinned(self):
        self._save()
        self.manager.pin_snapshot(1, approved_by="owner")
        pinned = self.manager.get_pinned()
        self.assertEqual(pinned.approved_by, "owner")

    def test_unset_approved_by_before_pin(self):
        self._save()
        data = json.loads(self.manager._snapshot_path(1).read_text())
        self.assertIsNone(data.get("approved_by"))


class TestHITLFailureWatermark(unittest.IsolatedAsyncioTestCase):
    """Bug 3 — watermark must not mark sessions processed when HITL delivery fails."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        self._patches = [
            patch("app.scheduler.handlers.bonsai.get_memory_subpath", return_value=self._tmp_dir),
            patch("app.scheduler.bonsai.get_memory_subpath", return_value=self._tmp_dir),
            patch("app.roles.role_manager.RoleManager.get", return_value=None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _make_session(self, role_id, session_id):
        chat_dir = Path(self._tmp_dir) / role_id / "chat_history"
        chat_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "session_id": session_id,
            "session_type": "owner_one_on_one",
            "last_active": "2026-06-14T10:00:00",
            "exchanges": [{"user": "always lead with growth for investors", "assistant": "noted"}],
        }
        (chat_dir / f"{session_id}.json").write_text(json.dumps(data))

    def _make_ctx(self):
        ctx = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        ctx._scheduler = None
        ctx.log = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        return ctx

    def _make_task(self, config):
        from app.scheduler.models import Task, TaskType, TaskPriority
        return Task(id="test", type=TaskType.GROWTH, priority=TaskPriority.LOW,
                    config=config, description="test", created_by="test")

    async def test_hitl_failure_sets_hitl_failed_flag(self):
        from app.scheduler.handlers.bonsai import BonsaiGrowthHandler, _read_watermark
        self._make_session("test_role", "s1")

        with patch("app.scheduler.handlers.bonsai.BonsaiGrowthHandler._send_hitl",
                   side_effect=RuntimeError("discord down")):
            handler = BonsaiGrowthHandler()
            task = self._make_task({"mode": "growth", "roles": ["test_role"], "notify_owner": True})
            result = await handler.execute(task, self._make_ctx())

        summaries = result.metrics["roles"]
        self.assertEqual(summaries[0]["status"], "hitl_failed")
        wm = _read_watermark("test_role")
        self.assertTrue(wm.get("hitl_failed"))

    async def test_hitl_failure_does_not_set_last_growth_run(self):
        from app.scheduler.handlers.bonsai import BonsaiGrowthHandler, _read_watermark
        self._make_session("test_role", "s1")

        with patch("app.scheduler.handlers.bonsai.BonsaiGrowthHandler._send_hitl",
                   side_effect=RuntimeError("discord down")):
            handler = BonsaiGrowthHandler()
            task = self._make_task({"mode": "growth", "roles": ["test_role"], "notify_owner": True})
            await handler.execute(task, self._make_ctx())

        wm = _read_watermark("test_role")
        # Sessions must NOT be marked processed — they need to be re-collected
        self.assertNotIn("last_growth_run", wm)

    async def test_next_run_retries_hitl_not_new_snapshot(self):
        from app.scheduler.handlers.bonsai import BonsaiGrowthHandler, _write_watermark, _read_watermark
        self._make_session("test_role", "s1")
        # Simulate a previous run that created v1 but failed to deliver HITL
        _write_watermark("test_role", {
            "pending_version": 1,
            "pending_report": "growth report text",
            "sessions_to_process": ["s1"],
            "hitl_failed": True,
        })
        from app.scheduler.bonsai import SnapshotManager, GrowthSnapshot
        sm = SnapshotManager("test_role")
        sm.save_snapshot(GrowthSnapshot("test_role", 1, {"core_values": {"score": 75}}, "test"))

        send_calls = []
        async def mock_send(self_arg, role_id, version, report, task_id, ctx):
            send_calls.append((role_id, version))

        with patch("app.scheduler.handlers.bonsai.BonsaiGrowthHandler._send_hitl", mock_send):
            handler = BonsaiGrowthHandler()
            task = self._make_task({"mode": "growth", "roles": ["test_role"], "notify_owner": True})
            result = await handler.execute(task, self._make_ctx())

        summaries = result.metrics["roles"]
        self.assertEqual(summaries[0]["status"], "hitl_retried")
        # Must retry v1, not create v2
        self.assertEqual(send_calls[0][1], 1)
        self.assertEqual(summaries[0]["snapshot_version"], 1)

    async def test_successful_hitl_sets_last_growth_run(self):
        from app.scheduler.handlers.bonsai import BonsaiGrowthHandler, _read_watermark
        self._make_session("test_role", "s1")

        async def mock_send(*args, **kwargs):
            pass

        with patch("app.scheduler.handlers.bonsai.BonsaiGrowthHandler._send_hitl", mock_send):
            handler = BonsaiGrowthHandler()
            task = self._make_task({"mode": "growth", "roles": ["test_role"], "notify_owner": True})
            await handler.execute(task, self._make_ctx())

        wm = _read_watermark("test_role")
        self.assertIn("last_growth_run", wm)
        self.assertFalse(wm.get("hitl_failed"))


if __name__ == "__main__":
    unittest.main()
