"""
Regression test for the gap-check resume bug.

Bug: when CapabilityGapChecker.check() found a blocker on a fresh task
start, AgenticExecutor.execute() paused the task via
TaskResult(waiting_for_input=...) BEFORE ever creating/saving a
TaskSession (session creation happened later, at the top of the agentic
loop). The scheduler (core.py) always sets
task.config["resume_from_task_id"] = task.id whenever a task goes to
waiting_for_input, so when the user replied ("Proceed anyway"),
_load_resume_messages() looked for a session that was never written and
returned None, causing execute() to hard-fail with:

  "Resume session 'X' not found for task X. Runtime must not fallback to
  fresh start for explicit resume requests."

This was hit repeatedly in production dispatching tasks whose goal text
contained a keyword (e.g. "playwright") that false-positive-triggered the
gap checker.

Fix: agentic_executor.py now saves a minimal system+goal session at the
gap-check pause point (before returning), so resume has something to load.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _make_task(task_id: str = "gap-check-task-1"):
    task = MagicMock()
    task.id = task_id
    task.dispatch_depth = 0
    task.pending_question = ""
    task.config = {
        "goal": "Open browser and navigate to the login page, then take a screenshot.",
        "max_iterations": 5,
    }
    task.resources = MagicMock()
    task.resources.max_iterations = 5
    task.resources.max_duration_seconds = 300
    task.resources.tier_preference = None
    return task


def _make_executor(tmp_path):
    """AgenticExecutor with real SessionStorage (writing to tmp_path) and real
    _record/_load_resume_messages, but everything else stubbed — enough to
    reach the capability-gap-check block."""
    from app.scheduler.agentic_executor import AgenticExecutor
    from app.scheduler.session_storage import SessionStorage
    from app.scheduler.capability_resolver import CapabilityResolver
    from app.scheduler.role_template_engine import RoleTemplateEngine
    from app.scheduler.capability_gap_checker import GapCheckResult

    exc = AgenticExecutor.__new__(AgenticExecutor)
    exc._policy_monitor = MagicMock()
    exc._policy_monitor.check.return_value = MagicMock(allowed=True, warn=False)
    exc._policy_monitor.validate_available_tools.return_value = []
    exc._policy_monitor.data_boundary = {}
    exc._tool_registry = MagicMock()
    exc._tool_registry.set_task_context = MagicMock()
    exc._tool_registry.get_tool.return_value = None
    exc._rm = MagicMock()
    # Real session storage against a temp dir -- this is the thing under test.
    exc._session_storage = SessionStorage(storage_dir=tmp_path)
    exc._role_id = None
    exc._tool_calls_made = 0
    exc._gate = MagicMock()
    exc._gate.reset_task = MagicMock()
    exc._mcp_client_manager = MagicMock()
    exc._mcp_client_manager.has_servers.return_value = False
    exc._mcp_tools_discovered = True
    exc._capability_resolver = CapabilityResolver()
    exc._role_template_engine = RoleTemplateEngine()
    exc._planning_manager = MagicMock()
    exc._planning_manager.get_prompt.return_value = None
    exc.logger = MagicMock()
    exc._log = lambda msg, level="info": None

    # Force a real blocker so the gap-check pause path is exercised.
    exc._gap_checker = MagicMock()
    exc._gap_checker.check.return_value = GapCheckResult(
        blockers=["Goal mentions 'open browser' but role has no 'browser' capability"]
    )
    exc._gap_checker._infer_categories = MagicMock(return_value=set())

    return exc


class TestGapCheckResumeSession(unittest.IsolatedAsyncioTestCase):

    async def test_gap_check_pause_persists_a_resumable_session(self, tmp_path=None):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            from app.scheduler.agentic_executor import AgenticExecutor

            exc = _make_executor(tmp_path)
            task = _make_task()

            result = await AgenticExecutor.execute(exc, task=task)

            # 1. Task actually paused for input (gap-check blocker fired).
            self.assertIsNotNone(result.waiting_for_input)
            self.assertFalse(result.success)

            # 2. A session now exists on disk for this task -- this is the fix.
            #    Before the fix, no file existed at this point at all.
            session = exc._session_storage.load_session(task.id)
            self.assertIsNotNone(
                session,
                "No session was persisted at the gap-check pause -- resume would "
                "hard-fail with 'Resume session not found' (the original bug).",
            )
            self.assertEqual(session.status, "waiting_for_input")
            roles = [m.role for m in session.messages]
            self.assertIn("system", roles)
            self.assertIn("user", roles)

            # 3. The exact method resume calls must now succeed instead of
            #    returning (None, 0).
            messages, _ = exc._load_resume_messages(task.id, "sys prompt")
            self.assertIsNotNone(
                messages,
                "_load_resume_messages returned None -- reply_to_task would still "
                "hard-fail with 'Resume session not found'.",
            )
            self.assertTrue(any(m["role"] == "user" for m in messages))


if __name__ == "__main__":
    unittest.main()
