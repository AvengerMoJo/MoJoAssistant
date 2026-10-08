"""Executors must not drop log lines when the scheduler wires no logger."""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock

from app.scheduler.log_util import emit


class TestEmit(unittest.TestCase):
    def test_uses_logger_when_present(self):
        lg = MagicMock()
        emit(lg, "X", "hello", "error")
        lg.error.assert_called_once_with("[X] hello")

    def test_prints_error_when_no_logger(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            emit(None, "AgenticExecutor", "LLM call failed: boom", "error")
        out = buf.getvalue()
        self.assertIn("[AgenticExecutor]", out)
        self.assertIn("ERROR", out)
        self.assertIn("LLM call failed: boom", out)

    def test_debug_is_quiet_without_logger(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            emit(None, "X", "noise", "debug")
        self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
