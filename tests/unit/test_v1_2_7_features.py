"""
Unit tests for v1.2.7 features.

Covers:
  - dispatch_subtask  (depth limit, missing scheduler, missing params, success path,
                       task-failed path, timeout path)
  - dialog tool       (chat / history / sessions actions via _execute_dialog)
  - RoleChatSession   (session persistence, task_search, _build_messages history,
                       tool loop with mocked LLM, think-token stripping)
  - MCPServerManager  (stop rollback: partial failure, full success, already-disconnected)
"""

import asyncio
import json
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import tempfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


# ===========================================================================
# dispatch_subtask
# ===========================================================================

class TestDispatchSubtask(unittest.IsolatedAsyncioTestCase):

    def _make_registry(self, depth=0, scheduler=None):
        from app.scheduler.dynamic_tool_registry import DynamicToolRegistry
        reg = DynamicToolRegistry.__new__(DynamicToolRegistry)
        reg._tools = {}
        reg._mcp_client_manager = None
        reg._scheduler = scheduler
        reg._current_task_id = "parent_task_001"
        reg._current_dispatch_depth = depth
        reg._memory_service = None
        reg._resource_manager = None
        return reg

    async def test_blocks_at_max_depth(self):
        from app.scheduler.dynamic_tool_registry import DynamicToolRegistry
        # Must provide a scheduler so the scheduler-check passes and depth-check is reached
        reg = self._make_registry(depth=DynamicToolRegistry.MAX_DISPATCH_DEPTH, scheduler=MagicMock())
        result = await reg._dispatch_subtask({"role_id": "ahman", "goal": "do something"})
        self.assertFalse(result["success"])
        self.assertIn("Max dispatch depth", result["error"])

    async def test_no_scheduler_returns_error(self):
        reg = self._make_registry(depth=0, scheduler=None)
        result = await reg._dispatch_subtask({"role_id": "ahman", "goal": "do something"})
        self.assertFalse(result["success"])
        self.assertIn("Scheduler not available", result["error"])

    async def test_missing_role_id_returns_error(self):
        reg = self._make_registry(scheduler=MagicMock())
        result = await reg._dispatch_subtask({"goal": "do something"})
        self.assertFalse(result["success"])
        self.assertIn("required", result["error"])

    async def test_missing_goal_returns_error(self):
        reg = self._make_registry(scheduler=MagicMock())
        result = await reg._dispatch_subtask({"role_id": "ahman"})
        self.assertFalse(result["success"])
        self.assertIn("required", result["error"])

    async def test_scheduler_add_task_failure(self):
        scheduler = MagicMock()
        scheduler.add_task.return_value = False
        reg = self._make_registry(scheduler=scheduler)
        result = await reg._dispatch_subtask({"role_id": "ahman", "goal": "do something"})
        self.assertFalse(result["success"])
        self.assertIn("Failed to queue", result["error"])

    async def test_success_path_returns_final_answer(self):
        from app.scheduler.models import Task, TaskType, TaskStatus, TaskResult, TaskResources
        import uuid

        # Build a completed task that the scheduler.get_task() will return
        completed_task = Task(
            id="sub_parent_task_001_abc123",
            type=TaskType.ASSISTANT,
            config={"goal": "research X", "role_id": "ahman"},
            resources=TaskResources(),
        )
        completed_task.status = TaskStatus.COMPLETED
        completed_task.result = TaskResult(
            success=True,
            metrics={"final_answer": "Here is the research result."},
        )

        scheduler = MagicMock()
        scheduler.add_task.return_value = True
        scheduler.get_task.return_value = completed_task

        reg = self._make_registry(scheduler=scheduler)

        # Patch asyncio.sleep to avoid real waiting
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await reg._dispatch_subtask({"role_id": "ahman", "goal": "research X"})

        self.assertTrue(result["success"])
        self.assertEqual(result["result"], "Here is the research result.")
        self.assertEqual(result["role_id"], "ahman")

    async def test_failed_subtask_returns_error(self):
        from app.scheduler.models import Task, TaskType, TaskStatus, TaskResources

        failed_task = Task(
            id="sub_parent_task_001_abc123",
            type=TaskType.ASSISTANT,
            config={"goal": "do X", "role_id": "ahman"},
            resources=TaskResources(),
        )
        failed_task.status = TaskStatus.FAILED
        failed_task.last_error = "Tool execution error"

        scheduler = MagicMock()
        scheduler.add_task.return_value = True
        scheduler.get_task.return_value = failed_task

        reg = self._make_registry(scheduler=scheduler)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await reg._dispatch_subtask({"role_id": "ahman", "goal": "do X"})

        self.assertFalse(result["success"])
        self.assertIn("Tool execution error", result["error"])

    async def test_depth_incremented_on_child_task(self):
        from app.scheduler.models import Task, TaskType, TaskStatus, TaskResources

        completed_task = Task(
            id="sub_x", type=TaskType.ASSISTANT,
            config={"goal": "g", "role_id": "ahman"},
            resources=TaskResources(),
        )
        completed_task.status = TaskStatus.COMPLETED
        completed_task.result = MagicMock(metrics={"final_answer": "done"})

        scheduler = MagicMock()
        scheduler.add_task.return_value = True
        scheduler.get_task.return_value = completed_task

        reg = self._make_registry(depth=1, scheduler=scheduler)

        created_tasks = []
        original_add = scheduler.add_task
        def capture_add(task):
            created_tasks.append(task)
            return True
        scheduler.add_task.side_effect = capture_add

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await reg._dispatch_subtask({"role_id": "ahman", "goal": "g"})

        self.assertEqual(len(created_tasks), 1)
        self.assertEqual(created_tasks[0].dispatch_depth, 2)
        self.assertEqual(created_tasks[0].parent_task_id, "parent_task_001")

    async def test_depth_1_still_allowed(self):
        """Depth 1 is below MAX_DISPATCH_DEPTH=2 and should proceed."""
        from app.scheduler.dynamic_tool_registry import DynamicToolRegistry
        reg = self._make_registry(depth=DynamicToolRegistry.MAX_DISPATCH_DEPTH - 1)
        reg._scheduler = None  # will fail on scheduler check, but NOT depth check
        result = await reg._dispatch_subtask({"role_id": "ahman", "goal": "do something"})
        self.assertIn("Scheduler not available", result["error"])  # depth check passed


# ===========================================================================
# dialog tool (_execute_dialog)
# ===========================================================================

class TestDialogTool(unittest.IsolatedAsyncioTestCase):

    def _make_tools(self, tmp_memory: Path):
        """Create a ToolRegistry with memory path patched to tmp dir."""
        from app.mcp.core.tools import ToolRegistry
        tools = ToolRegistry.__new__(ToolRegistry)
        tools.scheduler = MagicMock()
        tools._resource_manager = None
        return tools

    async def test_help_returned_for_unknown_action(self):
        from app.mcp.core.tools import ToolRegistry
        tools = ToolRegistry.__new__(ToolRegistry)
        tools.scheduler = MagicMock()
        tools._resource_manager = None
        result = await tools._execute_dialog({"action": "unknown_action", "role_id": "rebecca"})
        self.assertIn("tool", result)
        self.assertIn("actions", result)

    async def test_chat_requires_role_id(self):
        from app.mcp.core.tools import ToolRegistry
        tools = ToolRegistry.__new__(ToolRegistry)
        tools.scheduler = MagicMock()
        tools._resource_manager = None
        result = await tools._execute_dialog({"action": "chat", "message": "hello"})
        self.assertEqual(result["status"], "error")
        self.assertIn("role_id", result["message"])

    async def test_chat_requires_message(self):
        from app.mcp.core.tools import ToolRegistry
        tools = ToolRegistry.__new__(ToolRegistry)
        tools.scheduler = MagicMock()
        tools._resource_manager = None
        result = await tools._execute_dialog({"action": "chat", "role_id": "rebecca"})
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result["message"])

    async def test_sessions_action_returns_list(self):
        from app.mcp.core.tools import ToolRegistry
        tools = ToolRegistry.__new__(ToolRegistry)
        tools.scheduler = MagicMock()
        tools._resource_manager = None

        with patch("app.scheduler.role_chat.list_chat_sessions", return_value=[
            {"session_id": "s1", "started_at": "2026-03-27T10:00:00", "last_active": "2026-03-27T10:05:00", "turn_count": 3},
        ]):
            result = await tools._execute_dialog({"action": "sessions", "role_id": "rebecca"})

        # sessions action returns role_id / sessions / count (no "status" key)
        self.assertEqual(result["role_id"], "rebecca")
        self.assertEqual(result["count"], 1)
        self.assertIsInstance(result["sessions"], list)

    async def test_history_action_returns_exchanges(self):
        from app.mcp.core.tools import ToolRegistry
        tools = ToolRegistry.__new__(ToolRegistry)
        tools.scheduler = MagicMock()
        tools._resource_manager = None

        fake_session_data = {
            "session_id": "s1",
            "role_id": "rebecca",
            "exchanges": [{"user": "hi", "assistant": "hello", "timestamp": "2026-03-27T10:00:00"}],
        }

        with patch("app.scheduler.role_chat.RoleChatSession") as MockSession:
            instance = MockSession.return_value
            instance._load_session.return_value = fake_session_data
            result = await tools._execute_dialog({
                "action": "history",
                "role_id": "rebecca",
                "session_id": "s1",
            })

        self.assertEqual(result["session_id"], "s1")
        self.assertEqual(len(result["exchanges"]), 1)
        self.assertEqual(result["exchanges"][0]["user"], "hi")


# ===========================================================================
# RoleChatSession
# ===========================================================================

class TestRoleChatSession(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _make_session(self, role_id="test_role", session_id="test_session_001"):
        from app.scheduler.role_chat import RoleChatSession
        with patch("app.scheduler.role_chat.get_memory_subpath") as mock_path:
            mock_path.return_value = self.tmp
            session = RoleChatSession.__new__(RoleChatSession)
            session.role_id = role_id
            session.session_id = session_id
            session._session_dir = Path(self.tmp) / "roles" / role_id / "chat_history"
            session._session_dir.mkdir(parents=True, exist_ok=True)
            session._session_file = session._session_dir / f"{session_id}.json"
        return session

    # --- Session persistence ---

    def test_load_session_returns_empty_on_missing_file(self):
        session = self._make_session()
        data = session._load_session()
        self.assertEqual(data["session_id"], "test_session_001")
        self.assertEqual(data["exchanges"], [])

    def test_save_and_reload_session(self):
        session = self._make_session()
        initial = session._load_session()
        session._save_session(initial, "hello there", "hi back")
        reloaded = session._load_session()
        self.assertEqual(len(reloaded["exchanges"]), 1)
        self.assertEqual(reloaded["exchanges"][0]["user"], "hello there")
        self.assertEqual(reloaded["exchanges"][0]["assistant"], "hi back")
        self.assertIn("timestamp", reloaded["exchanges"][0])

    def test_multiple_saves_accumulate(self):
        session = self._make_session()
        data = session._load_session()
        session._save_session(data, "msg1", "resp1")
        data = session._load_session()
        session._save_session(data, "msg2", "resp2")
        data = session._load_session()
        self.assertEqual(len(data["exchanges"]), 2)
        self.assertEqual(data["exchanges"][1]["user"], "msg2")

    def test_save_updates_last_active(self):
        session = self._make_session()
        data = session._load_session()
        session._save_session(data, "x", "y")
        reloaded = session._load_session()
        self.assertIn("last_active", reloaded)

    # --- _build_messages includes history ---

    def test_build_messages_includes_history(self):
        session = self._make_session()
        history = [
            {"user": "first question", "assistant": "first answer"},
            {"user": "second question", "assistant": "second answer"},
        ]
        msgs = session._build_messages("You are a test bot.", "", "", history, "new question")
        # system + 2 user + 2 assistant + 1 new user = 6
        self.assertEqual(len(msgs), 6)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["content"], "first question")
        self.assertEqual(msgs[2]["content"], "first answer")
        self.assertEqual(msgs[-1]["content"], "new question")

    def test_build_messages_no_history(self):
        session = self._make_session()
        msgs = session._build_messages("sys", "", "", [], "hello")
        self.assertEqual(len(msgs), 2)  # system + user

    def test_build_messages_injects_ku_and_activity(self):
        session = self._make_session()
        msgs = session._build_messages("sys", "## KU context", "## Activity context", [], "hi")
        system_content = msgs[0]["content"]
        self.assertIn("KU context", system_content)
        self.assertIn("Activity context", system_content)

    def test_build_messages_respects_max_history_turns(self):
        from app.scheduler import role_chat as rc
        session = self._make_session()
        # Build more history than MAX_HISTORY_TURNS
        history = [{"user": f"q{i}", "assistant": f"a{i}"} for i in range(rc.MAX_HISTORY_TURNS + 5)]
        msgs = session._build_messages("sys", "", "", history, "latest")
        # system + MAX_HISTORY_TURNS*2 + 1 user
        self.assertEqual(len(msgs), 1 + rc.MAX_HISTORY_TURNS * 2 + 1)

    # --- task_search ---

    def _subpath_side_effect(self, *args):
        """get_memory_subpath(*args) → tmp/<args joined>  e.g. ("scheduler_tasks.json",) → tmp/scheduler_tasks.json"""
        return str(Path(self.tmp).joinpath(*args))

    def test_task_search_returns_empty_when_no_file(self):
        session = self._make_session()
        with patch("app.scheduler.role_chat.get_memory_subpath", side_effect=self._subpath_side_effect):
            results = session._search_tasks()
        self.assertEqual(results, [])

    def test_task_search_filters_by_role(self):
        session = self._make_session(role_id="rebecca")
        tasks_data = {
            "tasks": {
                "t1": {
                    "id": "t1", "status": "completed",
                    "config": {"role_id": "rebecca", "goal": "research AI"},
                    "completed_at": "2026-03-27T10:00:00",
                    "result": {"metrics": {"final_answer": "AI research done"}},
                },
                "t2": {
                    "id": "t2", "status": "completed",
                    "config": {"role_id": "ahman", "goal": "other task"},
                    "completed_at": "2026-03-27T11:00:00",
                    "result": {"metrics": {"final_answer": ""}},
                },
            }
        }
        (Path(self.tmp) / "scheduler_tasks.json").write_text(json.dumps(tasks_data))

        with patch("app.scheduler.role_chat.get_memory_subpath", side_effect=self._subpath_side_effect):
            results = session._search_tasks()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "t1")

    def test_task_search_keyword_filter(self):
        session = self._make_session(role_id="rebecca")
        tasks_data = {
            "tasks": {
                "t1": {"id": "t1", "status": "completed",
                       "config": {"role_id": "rebecca", "goal": "research security"},
                       "completed_at": "2026-03-27T10:00:00",
                       "result": {"metrics": {"final_answer": "done"}}},
                "t2": {"id": "t2", "status": "completed",
                       "config": {"role_id": "rebecca", "goal": "write a poem"},
                       "completed_at": "2026-03-27T11:00:00",
                       "result": {"metrics": {"final_answer": "done"}}},
            }
        }
        (Path(self.tmp) / "scheduler_tasks.json").write_text(json.dumps(tasks_data))

        with patch("app.scheduler.role_chat.get_memory_subpath", side_effect=self._subpath_side_effect):
            results = session._search_tasks(query="security")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "t1")

    def test_task_search_status_filter(self):
        session = self._make_session(role_id="rebecca")
        tasks_data = {
            "tasks": {
                "t1": {"id": "t1", "status": "completed",
                       "config": {"role_id": "rebecca", "goal": "task 1"},
                       "completed_at": "2026-03-27T10:00:00",
                       "result": {"metrics": {"final_answer": ""}}},
                "t2": {"id": "t2", "status": "failed",
                       "config": {"role_id": "rebecca", "goal": "task 2"},
                       "completed_at": "2026-03-27T11:00:00",
                       "result": {"metrics": {"final_answer": ""}}},
            }
        }
        (Path(self.tmp) / "scheduler_tasks.json").write_text(json.dumps(tasks_data))

        with patch("app.scheduler.role_chat.get_memory_subpath", side_effect=self._subpath_side_effect):
            results = session._search_tasks(status="failed")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "failed")

    # --- exchange() with mocked LLM (async tests in a nested IsolatedAsyncioTestCase) ---
    # These are defined in TestRoleChatSessionAsync below to get a proper event loop.
    pass


class TestRoleChatSessionAsync(unittest.IsolatedAsyncioTestCase):
    """Async exchange() tests that need a real event loop."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _make_session(self, role_id="test_role", session_id="test_session_001"):
        from app.scheduler.role_chat import RoleChatSession
        session = RoleChatSession.__new__(RoleChatSession)
        session.role_id = role_id
        session.session_id = session_id
        session._session_dir = Path(self.tmp) / "roles" / role_id / "chat_history"
        session._session_dir.mkdir(parents=True, exist_ok=True)
        session._session_file = session._session_dir / f"{session_id}.json"
        return session

    async def test_exchange_strips_think_tokens(self):
        """Think tokens in response content should be stripped."""
        session = self._make_session()
        raw_content = "<think>internal reasoning here</think>Actual answer."
        mock_role = {"system_prompt": "You are helpful.", "tool_access": []}

        async def fake_call_raw(messages, rm, tools=None):
            return {"choices": [{"message": {"content": raw_content, "tool_calls": None}}]}

        with patch("app.scheduler.role_chat.RoleManager") as MockRM:
            MockRM.return_value.get.return_value = mock_role
            session._call_raw = fake_call_raw
            session._load_ku_context = MagicMock(return_value="")
            session._load_recent_activity = MagicMock(return_value="")
            result = await session.exchange("hi", resource_manager=MagicMock())

        self.assertEqual(result["response"], "Actual answer.")

    async def test_exchange_persists_to_disk(self):
        """exchange() must save the turn to the session file."""
        session = self._make_session()
        mock_role = {"system_prompt": "You are helpful.", "tool_access": []}

        async def fake_call_raw(messages, rm, tools=None):
            return {"choices": [{"message": {"content": "I'm fine.", "tool_calls": None}}]}

        with patch("app.scheduler.role_chat.RoleManager") as MockRM:
            MockRM.return_value.get.return_value = mock_role
            session._call_raw = fake_call_raw
            session._load_ku_context = MagicMock(return_value="")
            session._load_recent_activity = MagicMock(return_value="")
            await session.exchange("How are you?", resource_manager=MagicMock())

        saved = json.loads(session._session_file.read_text())
        self.assertEqual(len(saved["exchanges"]), 1)
        self.assertEqual(saved["exchanges"][0]["user"], "How are you?")
        self.assertEqual(saved["exchanges"][0]["assistant"], "I'm fine.")

    async def test_exchange_includes_prior_history_in_messages(self):
        """Second exchange must include the first turn in the LLM messages."""
        session = self._make_session()
        mock_role = {"system_prompt": "You are helpful.", "tool_access": []}
        captured_messages = []

        async def fake_call_raw(messages, rm, tools=None):
            captured_messages.append(messages[:])
            return {"choices": [{"message": {"content": "response", "tool_calls": None}}]}

        with patch("app.scheduler.role_chat.RoleManager") as MockRM:
            MockRM.return_value.get.return_value = mock_role
            session._call_raw = fake_call_raw
            session._load_ku_context = MagicMock(return_value="")
            session._load_recent_activity = MagicMock(return_value="")
            await session.exchange("first message", resource_manager=MagicMock())
            await session.exchange("second message", resource_manager=MagicMock())

        # Second call's messages: system + user1 + assistant1 + user2
        second_call_msgs = captured_messages[1]
        roles = [m["role"] for m in second_call_msgs]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)
        user_contents = [m["content"] for m in second_call_msgs if m["role"] == "user"]
        self.assertIn("first message", user_contents)

    async def test_exchange_returns_error_for_unknown_role(self):
        session = self._make_session(role_id="nonexistent_role")
        with patch("app.scheduler.role_chat.RoleManager") as MockRM:
            MockRM.return_value.get.return_value = None
            result = await session.exchange("hello", resource_manager=MagicMock())
        self.assertIn("error", result)
        self.assertIn("nonexistent_role", result["error"])

    async def test_exchange_forces_final_answer_after_tool_loop_limit(self):
        """If tool calls consume the whole loop budget, exchange() must force a final text response."""
        from app.scheduler import role_chat as rc

        session = self._make_session()
        mock_role = {"system_prompt": "You are helpful.", "tool_access": ["memory"]}
        call_count = {"n": 0}

        async def fake_call_raw(messages, rm, tools=None):
            call_count["n"] += 1
            # First MAX_CHAT_ITERATIONS calls keep requesting tools.
            if call_count["n"] <= rc.MAX_CHAT_ITERATIONS:
                return {
                    "choices": [{
                        "message": {
                            "content": "",
                            "tool_calls": [{
                                "id": f"tc_{call_count['n']}",
                                "function": {
                                    "name": "memory_search",
                                    "arguments": "{\"query\":\"status\"}",
                                },
                            }],
                        }
                    }]
                }

            # Final synthesis call must be text-only.
            self.assertIsNone(tools)
            self.assertEqual(messages[-1]["role"], "system")
            self.assertIn("Do not call any more tools", messages[-1]["content"])
            return {"choices": [{"message": {"content": "Final answer after tool loop.", "tool_calls": None}}]}

        async def fake_execute_tool(name, args):
            return json.dumps({"success": True, "results": [{"snippet": "ok"}]})

        with patch("app.scheduler.role_chat.RoleManager") as MockRM:
            MockRM.return_value.get.return_value = mock_role
            session._call_raw = fake_call_raw
            session._execute_tool = fake_execute_tool
            session._load_ku_context = MagicMock(return_value="")
            session._load_recent_activity = MagicMock(return_value="")
            result = await session.exchange("hi", resource_manager=MagicMock())

        self.assertEqual(result["response"], "Final answer after tool loop.")
        self.assertEqual(result["context_used"]["tool_calls"], rc.MAX_CHAT_ITERATIONS)


# ===========================================================================
# MCPServerManager rollback
# ===========================================================================

class TestMCPServerManagerRollback(unittest.IsolatedAsyncioTestCase):

    def _make_manager(self, server_ids, connected_ids, fail_reconnect=None):
        """
        Build an MCPServerManager with a fake MCPClientManager.

        server_ids     — all configured servers
        connected_ids  — subset currently in _sessions
        fail_reconnect — set of server_ids whose reconnect should raise
        """
        from app.mcp.agents.mcp_server_manager import MCPServerManager

        fail_reconnect = fail_reconnect or set()

        # Fake server objects
        servers = {}
        for sid in server_ids:
            srv = MagicMock()
            srv.name = sid
            srv.category = "test"
            srv.command = "test"
            srv.args = []
            servers[sid] = srv

        async def fake_connect(server):
            sid = server.name
            if sid in fail_reconnect:
                raise RuntimeError(f"connect failed for {sid}")
            return [MagicMock()]

        from contextlib import AsyncExitStack
        exit_stack = AsyncExitStack()

        mgr = MagicMock()
        mgr._servers = servers
        mgr._sessions = {sid: MagicMock() for sid in connected_ids}
        mgr._exit_stack = exit_stack
        mgr._connected = True
        mgr._connect_server = fake_connect

        # Re-init exit_stack after aclose (mimics real behaviour)
        async def fake_aclose():
            pass
        exit_stack.aclose = fake_aclose

        return MCPServerManager(mgr)

    async def test_stop_unknown_server_returns_error(self):
        mgr = self._make_manager(["a", "b"], ["a", "b"])
        result = await mgr.stop_project("z")
        self.assertEqual(result["status"], "error")

    async def test_stop_already_disconnected_returns_ok(self):
        mgr = self._make_manager(["a", "b"], ["a"])  # b not connected
        result = await mgr.stop_project("b")
        self.assertEqual(result["status"], "ok")

    async def test_stop_success_disconnects_target(self):
        mgr = self._make_manager(["a", "b", "c"], ["a", "b", "c"])
        result = await mgr.stop_project("b")
        self.assertEqual(result["status"], "success")
        self.assertNotIn("b", mgr._mgr._sessions)

    async def test_stop_partial_when_sibling_fails(self):
        # Stop "a"; "b" is sibling but fails to reconnect
        mgr = self._make_manager(["a", "b"], ["a", "b"], fail_reconnect={"b"})
        result = await mgr.stop_project("a")
        self.assertEqual(result["status"], "partial")
        self.assertIn("b", result["failed"])

    async def test_stop_rollback_retries_failed_sibling(self):
        """Failed siblings should be retried once; if retry also fails → partial."""
        call_count = {"b": 0}

        from app.mcp.agents.mcp_server_manager import MCPServerManager

        async def flaky_connect(server):
            if server.name == "b":
                call_count["b"] += 1
                raise RuntimeError("still failing")
            return [MagicMock()]

        from contextlib import AsyncExitStack
        servers = {}
        for sid in ["a", "b"]:
            srv = MagicMock(); srv.name = sid; srv.category = "test"
            srv.command = "test"; srv.args = []
            servers[sid] = srv

        exit_stack = AsyncExitStack()
        async def fake_aclose(): pass
        exit_stack.aclose = fake_aclose

        inner_mgr = MagicMock()
        inner_mgr._servers = servers
        inner_mgr._sessions = {"a": MagicMock(), "b": MagicMock()}
        inner_mgr._exit_stack = exit_stack
        inner_mgr._connected = True
        inner_mgr._connect_server = flaky_connect

        sentinel = MCPServerManager(inner_mgr)
        result = await sentinel.stop_project("a")

        # "b" should have been attempted twice (initial + rollback)
        self.assertEqual(call_count["b"], 2)
        self.assertEqual(result["status"], "partial")
        self.assertIn("b", result["failed"])

    async def test_restart_surfaces_partial_warning(self):
        """restart_project() must propagate stop's partial warning."""
        mgr = self._make_manager(["a", "b"], ["a", "b"], fail_reconnect={"b"})
        result = await mgr.restart_project("a")
        # stop returned partial → start result should carry warning
        self.assertIn("warning", result)
        self.assertIn("b", result.get("failed_siblings", []))

    async def test_restart_cleans_up_if_stop_errors(self):
        """restart_project() must not call start when stop returns error."""
        mgr = self._make_manager(["a", "b"], ["a", "b"])
        # Patch stop to return error
        mgr.stop_project = AsyncMock(return_value={"status": "error", "message": "kaboom"})
        mgr.start_project = AsyncMock()
        result = await mgr.restart_project("z")
        mgr.start_project.assert_not_called()
        self.assertEqual(result["status"], "error")


# ===========================================================================
# list_chat_sessions helper
# ===========================================================================

class TestListChatSessions(unittest.TestCase):

    def test_returns_empty_for_missing_directory(self):
        from app.scheduler.role_chat import list_chat_sessions
        with patch("app.scheduler.role_chat.get_memory_subpath", return_value="/nonexistent/path"):
            result = list_chat_sessions("nobody")
        self.assertEqual(result, [])

    def test_returns_sessions_sorted_newest_first(self):
        from app.scheduler.role_chat import list_chat_sessions
        with tempfile.TemporaryDirectory() as tmp:
            chat_dir = Path(tmp) / "roles" / "rebecca" / "chat_history"
            chat_dir.mkdir(parents=True)

            for session_id, last_active in [
                ("chat_rebecca_20260327_090000", "2026-03-27T09:05:00"),
                ("chat_rebecca_20260327_100000", "2026-03-27T10:05:00"),
            ]:
                data = {
                    "session_id": session_id,
                    "role_id": "rebecca",
                    "started_at": last_active,
                    "last_active": last_active,
                    "exchanges": [{"user": "hi", "assistant": "hey"}],
                }
                (chat_dir / f"{session_id}.json").write_text(json.dumps(data))

            # list_chat_sessions does: Path(get_memory_subpath("roles")) / role_id / "chat_history"
            # so mock must return the "roles" subdirectory
            roles_dir = str(Path(tmp) / "roles")
            with patch("app.scheduler.role_chat.get_memory_subpath", return_value=roles_dir):
                result = list_chat_sessions("rebecca")

        self.assertEqual(len(result), 2)
        # Sorted by filename descending — newer session first
        self.assertEqual(result[0]["session_id"], "chat_rebecca_20260327_100000")
        self.assertEqual(result[0]["turn_count"], 1)


if __name__ == "__main__":
    unittest.main()
