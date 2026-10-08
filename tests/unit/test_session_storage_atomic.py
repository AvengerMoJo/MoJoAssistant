"""A crash while saving a session must not corrupt the file a resume would read (F19)."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app.scheduler.session_storage import SessionMessage, SessionStorage, TaskSession


def _session(n=1, status="running"):
    msgs = [SessionMessage("user", f"m{i}", datetime.now().isoformat(), i) for i in range(n)]
    return TaskSession("t1", status, msgs, datetime.now().isoformat())


class TestAtomicSave(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.storage = SessionStorage(self.dir)

    def test_roundtrip_and_no_temp_file_left(self):
        self.storage.save_session(_session(3))
        self.assertEqual(len(self.storage.load_session("t1").messages), 3)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["t1.json"])

    def test_failure_while_writing_leaves_the_previous_session_intact(self):
        self.storage.save_session(_session(2))
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.storage.save_session(_session(9))
        self.assertEqual(len(self.storage.load_session("t1").messages), 2)     # old, valid version survives
        json.loads((self.dir / "t1.json").read_text())

    def test_append_and_status_update_still_work(self):
        self.storage.save_session(_session(1))
        self.storage.append_message("t1", SessionMessage("assistant", "hi", datetime.now().isoformat(), 1))
        self.storage.update_status("t1", "failed", error_message="boom")
        s = self.storage.load_session("t1")
        self.assertEqual((len(s.messages), s.status, s.error_message), (2, "failed", "boom"))


if __name__ == "__main__":
    unittest.main()
