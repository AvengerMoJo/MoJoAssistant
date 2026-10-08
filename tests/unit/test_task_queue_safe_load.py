"""The task queue must never silently turn a damaged file into an empty schedule.

2026-10-08 review (F4): TaskQueue._load_from_disk caught any exception and set tasks = {}; the next
save then overwrote the damaged file, erasing every recurring job that is not seeded from config
(12+ of 15). A single unparseable task was also dropped silently.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from app.scheduler.models import Task, TaskType
from app.scheduler.queue import QueueLoadError, TaskQueue


def _task(tid, cron=None):
    return Task(id=tid, type=TaskType.INTERNAL_ASSIGNMENT, config={"goal": "g"}, cron_expression=cron)


class TestSafeLoad(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "scheduler_tasks.json"

    def _queue_with(self, *ids):
        q = TaskQueue(str(self.path))
        for i in ids:
            q.add(_task(i, cron="0 6 * * *"))
        return q

    def test_healthy_roundtrip(self):
        self._queue_with("a", "b")
        q2 = TaskQueue(str(self.path))
        self.assertEqual(set(q2.tasks), {"a", "b"})

    def test_corrupt_file_is_quarantined_and_restored_from_backup(self):
        q = self._queue_with("a")                        # first save also writes the backup
        bak = self.dir / "scheduler_tasks.json.bak"
        old = time.time() - TaskQueue.BACKUP_MAX_AGE_SECONDS - 60
        os.utime(bak, (old, old))
        q.add(_task("b", cron="0 6 * * *"))              # stale backup -> refreshed with {a, b}
        self.path.write_text('{"tasks": {"a": ', encoding="utf-8")   # truncated JSON
        q2 = TaskQueue(str(self.path))
        self.assertEqual(set(q2.tasks), {"a", "b"})                 # schedule survives
        corrupt = list(self.dir.glob("scheduler_tasks.json.corrupt-*"))
        self.assertEqual(len(corrupt), 1)
        self.assertIn('"a": ', corrupt[0].read_text())              # the damaged evidence is kept
        json.loads(self.path.read_text())                           # live file is valid again

    def test_changes_newer_than_the_backup_are_the_only_thing_lost(self):
        q = self._queue_with("a")
        q.add(_task("newer"))                            # saved within the backup window -> not in the backup
        self.path.write_text("{", encoding="utf-8")
        self.assertEqual(set(TaskQueue(str(self.path)).tasks), {"a"})

    def test_corrupt_file_without_backup_refuses_to_start(self):
        self.path.write_text("not json at all", encoding="utf-8")
        with self.assertRaises(QueueLoadError) as cm:
            TaskQueue(str(self.path))
        self.assertIn("no backup", str(cm.exception))
        self.assertTrue(list(self.dir.glob("scheduler_tasks.json.corrupt-*")))   # not overwritten, not lost
        self.assertFalse(self.path.exists())                                      # and no empty file written over it

    def test_corrupt_file_and_corrupt_backup_refuses_to_start(self):
        self._queue_with("a")
        self.path.write_text("{", encoding="utf-8")
        (self.dir / "scheduler_tasks.json.bak").write_text("also bad", encoding="utf-8")
        with self.assertRaises(QueueLoadError):
            TaskQueue(str(self.path))

    def test_wrong_shape_counts_as_corrupt(self):
        self._queue_with("a")
        self.path.write_text(json.dumps({"tasks": ["not", "a", "dict"]}), encoding="utf-8")
        self.assertEqual(set(TaskQueue(str(self.path)).tasks), {"a"})

    def test_unparseable_task_is_kept_unchanged_across_saves(self):
        self._queue_with("good")
        data = json.loads(self.path.read_text())
        data["tasks"]["weird"] = {"id": "weird", "type": "a-future-task-type", "extra": [1, 2]}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        q = TaskQueue(str(self.path))
        self.assertEqual(set(q.tasks), {"good"})
        q.add(_task("later"))                                       # a save happens
        on_disk = json.loads(self.path.read_text())["tasks"]
        self.assertEqual(on_disk["weird"], {"id": "weird", "type": "a-future-task-type", "extra": [1, 2]})
        self.assertEqual(set(on_disk), {"good", "weird", "later"})

    def test_backup_is_refreshed_only_when_old(self):
        q = self._queue_with("a")
        bak = self.dir / "scheduler_tasks.json.bak"
        first = bak.stat().st_mtime
        q.add(_task("b"))                                           # fresh backup -> not rewritten
        self.assertEqual(bak.stat().st_mtime, first)
        self.assertEqual(set(json.loads(bak.read_text())["tasks"]), {"a"})
        old = time.time() - TaskQueue.BACKUP_MAX_AGE_SECONDS - 60
        os.utime(bak, (old, old))
        q.add(_task("c"))                                           # stale backup -> refreshed
        self.assertEqual(set(json.loads(bak.read_text())["tasks"]), {"a", "b", "c"})


if __name__ == "__main__":
    unittest.main()
