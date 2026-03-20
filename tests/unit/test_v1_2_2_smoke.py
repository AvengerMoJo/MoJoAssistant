"""
v1.2.2 smoke tests

Covers:
  - AttentionClassifier per-source routing
  - Agent hub dispatcher normalisation (type→agent_type, agent_id→identifier)
  - Scheduler hub add normalisation (type→task_type, top-level goal/role_id→config)
  - CodingAgentExecutor routing (role with executor="coding_agent" → CodingAgentExecutor)

Run with:
    python -m pytest tests/unit/test_v1_2_2_smoke.py -v
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# AttentionClassifier — per-source routing
# ---------------------------------------------------------------------------

class TestAttentionClassifierPerSource(unittest.TestCase):
    def setUp(self):
        # Reset module-level rule cache so tests are isolated from disk config.
        import app.mcp.adapters.attention_classifier as mod
        mod._SOURCE_RULES = None

    def _classify(self, event, source_rules=None):
        import app.mcp.adapters.attention_classifier as mod
        if source_rules is not None:
            mod._SOURCE_RULES = source_rules
        return mod.AttentionClassifier.classify(event)

    # Base rules (no source)

    def test_critical_severity_is_5(self):
        self.assertEqual(self._classify({"severity": "critical"}), 5)

    def test_waiting_for_input_is_4(self):
        self.assertEqual(self._classify({"event_type": "task_waiting_for_input"}), 4)

    def test_task_failed_is_3(self):
        self.assertEqual(self._classify({"event_type": "task_failed", "severity": "error"}), 3)

    def test_completed_with_notify_is_2(self):
        self.assertEqual(
            self._classify({"event_type": "task_completed", "notify_user": True}), 2
        )

    def test_notify_only_is_1(self):
        self.assertEqual(self._classify({"notify_user": True}), 1)

    def test_default_is_0(self):
        self.assertEqual(self._classify({}), 0)

    # Per-source: dreaming capped at 1

    def test_dreaming_task_failed_capped_at_1(self):
        rules = {"dreaming": {"max_level": 1}}
        event = {"event_type": "task_failed", "severity": "error", "task_type": "dreaming"}
        # base=3, capped to 1
        self.assertEqual(self._classify(event, rules), 1)

    def test_dreaming_completed_with_notify_capped_at_1(self):
        rules = {"dreaming": {"max_level": 1}}
        event = {"event_type": "task_completed", "notify_user": True, "task_type": "dreaming"}
        # base=2, capped to 1
        self.assertEqual(self._classify(event, rules), 1)

    def test_dreaming_waiting_for_input_capped_at_1(self):
        rules = {"dreaming": {"max_level": 1}}
        event = {"event_type": "task_waiting_for_input", "task_type": "dreaming"}
        # base=4, capped to 1 — dreaming should never ask for input, but if it does, stays quiet
        self.assertEqual(self._classify(event, rules), 1)

    # Per-source: agent floor at 2

    def test_agent_background_event_raised_to_2(self):
        rules = {"agent": {"min_level": 2}}
        event = {"task_type": "agent"}  # base=0
        self.assertEqual(self._classify(event, rules), 2)

    def test_agent_waiting_for_input_stays_4(self):
        rules = {"agent": {"min_level": 2}}
        event = {"event_type": "task_waiting_for_input", "task_type": "agent"}
        # base=4, min=2 → stays 4
        self.assertEqual(self._classify(event, rules), 4)

    # Per-source: unknown source — no override

    def test_unknown_source_no_override(self):
        rules = {"dreaming": {"max_level": 1}}
        event = {"event_type": "task_failed", "severity": "error", "task_type": "assistant"}
        # no rule for "assistant" → base rules apply
        self.assertEqual(self._classify(event, rules), 3)

    # Critical is always 5 — source caps cannot suppress critical

    def test_dreaming_critical_capped_but_stays_1(self):
        """dreaming max_level=1 caps critical to 1 — by design, dreaming cannot be critical."""
        rules = {"dreaming": {"max_level": 1}}
        event = {"severity": "critical", "task_type": "dreaming"}
        self.assertEqual(self._classify(event, rules), 1)

    def test_reload_rules_replaces_cache(self):
        import app.mcp.adapters.attention_classifier as mod
        # Force a bad value into cache
        mod._SOURCE_RULES = {"dreaming": {"max_level": 99}}
        mod.AttentionClassifier.reload_rules()
        # After reload the stale value is gone; dreaming rule should be back to default (max 1)
        self.assertNotEqual(mod._SOURCE_RULES.get("dreaming", {}).get("max_level"), 99)


# ---------------------------------------------------------------------------
# Agent hub dispatcher normalisation
# ---------------------------------------------------------------------------

class TestAgentHubNormalisation(unittest.IsolatedAsyncioTestCase):
    """
    Verify that the agent hub translates MCP-schema keys to internal keys
    before dispatching: type→agent_type, agent_id→identifier.
    """

    async def _run_agent_hub(self, args: dict) -> dict:
        from app.mcp.core.tools import ToolRegistry
        registry = ToolRegistry.__new__(ToolRegistry)
        registry._agent_managers = {}
        registry._log = lambda *a, **k: None

        # Capture the normalised args passed to _execute_agent_start
        captured = {}

        async def fake_execute_agent_start(a):
            captured.update(a)
            return {"status": "ok"}

        registry._execute_agent_start = fake_execute_agent_start
        await registry._execute_agent_hub(args)
        return captured

    async def test_type_normalised_to_agent_type(self):
        captured = await self._run_agent_hub(
            {"action": "start", "type": "opencode", "agent_id": "abc123"}
        )
        self.assertEqual(captured.get("agent_type"), "opencode")

    async def test_agent_id_normalised_to_identifier(self):
        captured = await self._run_agent_hub(
            {"action": "start", "type": "opencode", "agent_id": "abc123"}
        )
        self.assertEqual(captured.get("identifier"), "abc123")

    async def test_existing_agent_type_not_overwritten(self):
        """If caller already passes agent_type, it should be preserved."""
        captured = await self._run_agent_hub(
            {"action": "start", "agent_type": "opencode", "agent_id": "abc123"}
        )
        self.assertEqual(captured.get("agent_type"), "opencode")


# ---------------------------------------------------------------------------
# Scheduler hub add normalisation
# ---------------------------------------------------------------------------

class TestSchedulerHubAddNormalisation(unittest.IsolatedAsyncioTestCase):
    """
    Verify that scheduler(action="add") normalises:
      type        → task_type
      goal        → config.goal
      role_id     → config.role_id
    """

    async def _run_scheduler_add(self, args: dict) -> dict:
        from app.mcp.core.tools import ToolRegistry
        registry = ToolRegistry.__new__(ToolRegistry)
        registry.scheduler = MagicMock()
        registry._log = lambda *a, **k: None

        captured = {}

        async def fake_add_task(a):
            captured.update(a)
            return {"status": "success", "message": "ok", "task": {}}

        registry._execute_scheduler_add_task = fake_add_task
        await registry._execute_scheduler_hub(args)
        return captured

    async def test_type_to_task_type(self):
        captured = await self._run_scheduler_add(
            {"action": "add", "type": "assistant", "goal": "do something"}
        )
        self.assertEqual(captured.get("task_type"), "assistant")

    async def test_goal_promoted_to_config(self):
        captured = await self._run_scheduler_add(
            {"action": "add", "type": "assistant", "goal": "do something"}
        )
        self.assertEqual(captured.get("config", {}).get("goal"), "do something")

    async def test_role_id_promoted_to_config(self):
        captured = await self._run_scheduler_add(
            {"action": "add", "type": "assistant", "goal": "do something", "role_id": "popo"}
        )
        self.assertEqual(captured.get("config", {}).get("role_id"), "popo")

    async def test_existing_task_type_not_overwritten(self):
        captured = await self._run_scheduler_add(
            {"action": "add", "task_type": "dreaming", "type": "assistant"}
        )
        self.assertEqual(captured.get("task_type"), "dreaming")

    async def test_existing_config_goal_not_overwritten(self):
        captured = await self._run_scheduler_add({
            "action": "add",
            "type": "assistant",
            "goal": "outer goal",
            "config": {"goal": "inner goal"},
        })
        self.assertEqual(captured.get("config", {}).get("goal"), "inner goal")


# ---------------------------------------------------------------------------
# CodingAgentExecutor routing
# ---------------------------------------------------------------------------

class TestCodingAgentExecutorRouting(unittest.IsolatedAsyncioTestCase):
    """
    Verify that _execute_agentic routes to CodingAgentExecutor when the
    role has executor="coding_agent", and NOT when it doesn't.
    """

    async def test_routes_to_coding_agent_executor(self):
        from app.scheduler.executor import TaskExecutor as Executor
        from app.scheduler.models import Task, TaskType

        executor = Executor.__new__(Executor)
        executor._log = lambda *a, **k: None
        executor._get_agentic_executor = MagicMock()

        coding_exec = AsyncMock()
        coding_exec.execute = AsyncMock(
            return_value=MagicMock(success=True, waiting_for_input=None)
        )
        executor._get_coding_agent_executor = MagicMock(return_value=coding_exec)

        task = Task(id="t1", type=TaskType.ASSISTANT, config={"goal": "test", "role_id": "popo"})

        role_with_coding = {"executor": "coding_agent", "id": "popo"}
        with patch("app.roles.role_manager.RoleManager") as MockRM:
            MockRM.return_value.get.return_value = role_with_coding
            await executor._execute_agentic(task)

        coding_exec.execute.assert_called_once_with(task)
        executor._get_agentic_executor.assert_not_called()

    async def test_regular_role_uses_agentic_executor(self):
        from app.scheduler.executor import TaskExecutor as Executor
        from app.scheduler.models import Task, TaskType

        executor = Executor.__new__(Executor)
        executor._log = lambda *a, **k: None

        agentic_exec = AsyncMock()
        agentic_exec.execute = AsyncMock(
            return_value=MagicMock(success=True, waiting_for_input=None)
        )
        executor._get_agentic_executor = MagicMock(return_value=agentic_exec)
        executor._get_coding_agent_executor = MagicMock()

        task = Task(
            id="t2", type=TaskType.ASSISTANT, config={"goal": "test", "role_id": "rebecca"}
        )

        role_no_executor = {"id": "rebecca"}
        with patch("app.roles.role_manager.RoleManager") as MockRM:
            MockRM.return_value.get.return_value = role_no_executor
            await executor._execute_agentic(task)

        agentic_exec.execute.assert_called_once_with(task)
        executor._get_coding_agent_executor.assert_not_called()

    async def test_no_role_uses_agentic_executor(self):
        from app.scheduler.executor import TaskExecutor as Executor
        from app.scheduler.models import Task, TaskType

        executor = Executor.__new__(Executor)
        executor._log = lambda *a, **k: None

        agentic_exec = AsyncMock()
        agentic_exec.execute = AsyncMock(
            return_value=MagicMock(success=True, waiting_for_input=None)
        )
        executor._get_agentic_executor = MagicMock(return_value=agentic_exec)
        executor._get_coding_agent_executor = MagicMock()

        task = Task(id="t3", type=TaskType.ASSISTANT, config={"goal": "test"})

        await executor._execute_agentic(task)

        agentic_exec.execute.assert_called_once_with(task)
        executor._get_coding_agent_executor.assert_not_called()


# ---------------------------------------------------------------------------
# CodingAgentExecutor — send_message polling fix
# ---------------------------------------------------------------------------

class TestCodingAgentSendPolling(unittest.IsolatedAsyncioTestCase):
    """
    Verify that _send_with_permission_watch polls for completion after the
    fire-and-forget send_message HTTP call returns.
    """

    def _make_executor(self):
        from app.scheduler.coding_agent_executor import CodingAgentExecutor
        ex = CodingAgentExecutor.__new__(CodingAgentExecutor)
        ex._log = lambda *a, **k: None
        ex._pending_permission = None
        ex._waiting_for_input_question = None
        return ex

    async def test_polls_until_no_running_parts(self):
        """send_message returns immediately; polling detects completion after 1 poll cycle."""
        from app.scheduler.coding_agent_executor import CodingAgentExecutor

        ex = self._make_executor()

        running_msgs = [
            {"role": "assistant", "parts": [{"type": "tool-invocation", "state": {"status": "running"}}]}
        ]
        done_msgs = [
            {"role": "assistant", "parts": [{"type": "text", "text": "Done."}]}
        ]

        backend = AsyncMock()
        backend.send_message = AsyncMock(return_value={"id": "m1"})
        backend.get_messages = AsyncMock(side_effect=[
            [],            # initial count snapshot
            running_msgs,  # first poll — still running
            done_msgs,     # second poll — complete
        ])

        result = await ex._send_and_wait_for_completion(backend, "sess1", "do it")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"], "Done.")
        self.assertEqual(backend.get_messages.call_count, 3)

    async def test_has_running_parts_detects_running_status(self):
        from app.scheduler.coding_agent_executor import CodingAgentExecutor

        msgs_running = [{"parts": [{"type": "tool-invocation", "state": {"status": "running"}}]}]
        msgs_done = [{"parts": [{"type": "text", "state": {"status": "completed"}}]}]
        msgs_no_state = [{"parts": [{"type": "text"}]}]

        self.assertTrue(CodingAgentExecutor._has_running_parts(msgs_running))
        self.assertFalse(CodingAgentExecutor._has_running_parts(msgs_done))
        self.assertFalse(CodingAgentExecutor._has_running_parts(msgs_no_state))
        self.assertFalse(CodingAgentExecutor._has_running_parts([]))

    async def test_permission_wins_over_completion(self):
        """Permission arriving concurrently with polling causes permission path."""
        from app.scheduler.coding_agent_executor import CodingAgentExecutor

        ex = self._make_executor()

        done_msgs = [{"role": "assistant", "parts": [{"type": "text", "text": "Done."}]}]
        backend = AsyncMock()
        backend.send_message = AsyncMock(return_value={"id": "m1"})
        # get_messages: initial snapshot + two fast polls returning done
        backend.get_messages = AsyncMock(return_value=done_msgs)

        perm_event = {"id": "perm1", "type": "tool", "title": "Write /tmp/file.txt"}

        async def fake_subscribe(_session_id):
            yield perm_event

        backend.subscribe_permissions = fake_subscribe

        # Patch _poll_for_completion to be slow so permission wins
        async def slow_poll(*a, **k):
            await asyncio.sleep(10)
            return done_msgs

        ex._poll_for_completion = slow_poll

        result = await ex._send_with_permission_watch(backend, "sess1", "do it")
        self.assertEqual(result["status"], "permission_required")
        self.assertEqual(result["permission_id"], "perm1")
        self.assertIsNotNone(ex._pending_permission)


if __name__ == "__main__":
    unittest.main()
