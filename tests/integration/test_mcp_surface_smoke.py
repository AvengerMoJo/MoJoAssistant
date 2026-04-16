"""
MCP Surface Smoke Test — Zero to Hero

Verifies every visible MCP tool (the 12-tool surface) responds correctly
for both happy-path calls and expected error cases.

Run before every release:
    pytest tests/integration/test_mcp_surface_smoke.py -v

Design:
- Tests call registry.execute(name, args) directly — no HTTP, no MCP client
- Each test is independent; registry is shared via session fixture
- PASS = tool returns expected structure
- EXPECTED_FAIL = tool returns {"status": "error"} for invalid input (also a PASS)
- TRUE_FAIL = tool crashes, returns wrong structure, or placeholder response
"""

import asyncio
import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

os.environ.setdefault("ENVIRONMENT", "ci")
os.environ.setdefault("MEMORY_PATH", "/tmp/mojo-smoke-test")
os.environ.setdefault("EMBEDDING_MODEL", "all-MiniLM-L6-v2")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def registry():
    """Single ToolRegistry instance shared across all tests."""
    from app.services.hybrid_memory_service import HybridMemoryService
    from app.mcp.core.tools import ToolRegistry

    memory_path = "/tmp/mojo-smoke-test"
    Path(memory_path).mkdir(parents=True, exist_ok=True)

    memory_service = HybridMemoryService()
    reg = ToolRegistry(memory_service=memory_service)
    yield reg
    # Graceful shutdown
    try:
        reg._stop_scheduler_daemon()
    except Exception:
        pass
    try:
        reg._push_manager.stop_all()
    except Exception:
        pass


def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.new_event_loop().run_until_complete(coro)


def assert_not_placeholder(result, tool_name):
    assert result.get("status") != "placeholder", (
        f"{tool_name} returned placeholder — tool is disabled or not wired up"
    )


def assert_no_crash(result):
    assert isinstance(result, dict), f"Tool returned non-dict: {type(result)}"


def assert_success(result, tool_name):
    assert_not_placeholder(result, tool_name)
    assert_no_crash(result)
    assert result.get("status") != "error", (
        f"{tool_name} returned unexpected error: {result.get('message')}"
    )


def assert_expected_error(result, tool_name, contains=None):
    """Tool should return an error — that's the correct behaviour for bad input."""
    assert_not_placeholder(result, tool_name)
    assert_no_crash(result)
    assert result.get("status") == "error", (
        f"{tool_name} should have returned error but got: {result}"
    )
    if contains:
        assert contains.lower() in str(result.get("message", "")).lower(), (
            f"{tool_name} error message should contain '{contains}', got: {result.get('message')}"
        )


def assert_help_menu(result, tool_name, expected_actions=None):
    """Hub called with no action should return a help menu with 'actions' key."""
    assert_not_placeholder(result, tool_name)
    assert_no_crash(result)
    assert "actions" in result, (
        f"{tool_name}() should return help menu with 'actions' key, got: {result}"
    )
    if expected_actions:
        for action in expected_actions:
            assert action in result["actions"], (
                f"{tool_name} help menu missing action '{action}'"
            )


# ---------------------------------------------------------------------------
# 1. get_context
# ---------------------------------------------------------------------------

class TestGetContext:
    def test_orientation_default(self, registry):
        result = run(registry.execute("get_context", {}))
        assert_success(result, "get_context")
        assert "timestamp" in result
        assert "date" in result
        assert "day_of_week" in result
        assert "time" in result
        assert "recent_memory" in result

    def test_orientation_explicit_type(self, registry):
        result = run(registry.execute("get_context", {"type": "orientation"}))
        assert_success(result, "get_context[orientation]")
        assert "timestamp" in result

    def test_attention_type(self, registry):
        result = run(registry.execute("get_context", {"type": "attention"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "get_context[attention]")
        # Returns grouped inbox — may be empty but must have cursor or be a valid structure
        assert isinstance(result, dict)

    def test_events_type(self, registry):
        result = run(registry.execute("get_context", {"type": "events", "limit": 5}))
        assert_no_crash(result)
        assert_not_placeholder(result, "get_context[events]")
        assert "events" in result or "status" in result  # may be empty list

    def test_task_session_missing_task_id(self, registry):
        result = run(registry.execute("get_context", {"type": "task_session"}))
        assert_expected_error(result, "get_context[task_session missing id]", contains="task_id")

    def test_task_session_nonexistent(self, registry):
        result = run(registry.execute("get_context", {
            "type": "task_session", "task_id": "nonexistent_task_smoke_test"
        }))
        # Should return error or not-found, not crash
        assert_no_crash(result)
        assert_not_placeholder(result, "get_context[task_session nonexistent]")


# ---------------------------------------------------------------------------
# 2. search_memory
# ---------------------------------------------------------------------------

class TestSearchMemory:
    def test_basic_search(self, registry):
        result = run(registry.execute("search_memory", {"query": "test smoke query"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "search_memory")
        # May return empty results but must not error
        assert result.get("status") != "error"

    def test_search_conversations_only(self, registry):
        result = run(registry.execute("search_memory", {
            "query": "test", "types": ["conversations"]
        }))
        assert_no_crash(result)
        assert result.get("status") != "error"

    def test_search_documents_only(self, registry):
        result = run(registry.execute("search_memory", {
            "query": "test", "types": ["documents"]
        }))
        assert_no_crash(result)
        assert result.get("status") != "error"

    def test_missing_query(self, registry):
        result = run(registry.execute("search_memory", {}))
        assert_expected_error(result, "search_memory[no query]", contains="query")


# ---------------------------------------------------------------------------
# 3. add_conversation
# ---------------------------------------------------------------------------

class TestAddConversation:
    def test_happy_path(self, registry):
        result = run(registry.execute("add_conversation", {
            "user_message": "smoke test user message",
            "assistant_message": "smoke test assistant reply",
        }))
        assert_success(result, "add_conversation")

    def test_missing_user_message(self, registry):
        result = run(registry.execute("add_conversation", {
            "assistant_message": "no user message"
        }))
        # Should error — user_message is required
        assert_no_crash(result)
        assert_not_placeholder(result, "add_conversation[no user_message]")

    def test_missing_assistant_message(self, registry):
        result = run(registry.execute("add_conversation", {
            "user_message": "no assistant message"
        }))
        assert_no_crash(result)
        assert_not_placeholder(result, "add_conversation[no assistant_message]")


# ---------------------------------------------------------------------------
# 4. reply_to_task
# ---------------------------------------------------------------------------

class TestReplyToTask:
    def test_nonexistent_task(self, registry):
        result = run(registry.execute("reply_to_task", {
            "task_id": "nonexistent_smoke_task",
            "reply": "test reply",
        }))
        # Should return error — task doesn't exist
        assert_no_crash(result)
        assert_not_placeholder(result, "reply_to_task[nonexistent]")
        assert result.get("status") == "error"

    def test_missing_task_id(self, registry):
        result = run(registry.execute("reply_to_task", {"reply": "test"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "reply_to_task[no task_id]")


# ---------------------------------------------------------------------------
# 5. memory hub
# ---------------------------------------------------------------------------

class TestMemoryHub:
    def test_help_menu(self, registry):
        result = run(registry.execute("memory", {}))
        assert_help_menu(result, "memory", expected_actions=[
            "end_conversation", "list_conversations", "remove_conversation",
            "remove_conversations", "add_documents", "list_documents",
            "remove_document", "stats", "toggle_multi_model",
        ])

    def test_list_conversations(self, registry):
        result = run(registry.execute("memory", {"action": "list_conversations", "limit": 5}))
        assert_no_crash(result)
        assert_not_placeholder(result, "memory[list_conversations]")

    def test_stats(self, registry):
        result = run(registry.execute("memory", {"action": "stats"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "memory[stats]")

    def test_add_documents(self, registry):
        result = run(registry.execute("memory", {
            "action": "add_documents",
            "documents": [{"content": "smoke test document content"}],
        }))
        assert_no_crash(result)
        assert_not_placeholder(result, "memory[add_documents]")

    def test_list_documents(self, registry):
        result = run(registry.execute("memory", {"action": "list_documents", "limit": 5}))
        assert_no_crash(result)
        assert_not_placeholder(result, "memory[list_documents]")

    def test_remove_document_missing_id(self, registry):
        result = run(registry.execute("memory", {"action": "remove_document"}))
        assert_expected_error(result, "memory[remove_document no id]", contains="id")

    def test_remove_conversation_missing_id(self, registry):
        result = run(registry.execute("memory", {"action": "remove_conversation"}))
        assert_expected_error(result, "memory[remove_conversation no id]", contains="id")

    def test_unknown_action(self, registry):
        result = run(registry.execute("memory", {"action": "nonexistent_action"}))
        assert_no_crash(result)
        assert "actions" in result  # falls back to help menu with error note
        assert "error" in result

    def test_end_conversation(self, registry):
        result = run(registry.execute("memory", {"action": "end_conversation"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "memory[end_conversation]")


# ---------------------------------------------------------------------------
# 7. knowledge hub
# ---------------------------------------------------------------------------

class TestKnowledgeHub:
    def test_help_menu(self, registry):
        result = run(registry.execute("knowledge", {}))
        assert_help_menu(result, "knowledge", expected_actions=[
            "list_repos", "add_repo", "get_file",
        ])

    def test_list_repos(self, registry):
        result = run(registry.execute("knowledge", {"action": "list_repos"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "knowledge[list_repos]")

    def test_add_repo_missing_params(self, registry):
        result = run(registry.execute("knowledge", {"action": "add_repo", "name": "test"}))
        assert_expected_error(result, "knowledge[add_repo missing params]")

    def test_get_file_missing_params(self, registry):
        result = run(registry.execute("knowledge", {"action": "get_file"}))
        assert_expected_error(result, "knowledge[get_file missing params]")

    def test_unknown_action(self, registry):
        result = run(registry.execute("knowledge", {"action": "bad_action"}))
        assert_no_crash(result)
        assert "actions" in result
        assert "error" in result


# ---------------------------------------------------------------------------
# 8. config hub
# ---------------------------------------------------------------------------

class TestConfigHub:
    def test_help_menu(self, registry):
        result = run(registry.execute("config", {}))
        assert_help_menu(result, "config", expected_actions=[
            "get", "set", "modules", "resource_status", "doctor",
            "resource_approve", "llm_models",
        ])

    def test_modules(self, registry):
        result = run(registry.execute("config", {"action": "modules"}))
        assert_success(result, "config[modules]")
        assert "modules" in result

    def test_resource_status(self, registry):
        result = run(registry.execute("config", {"action": "resource_status"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "config[resource_status]")

    def test_doctor(self, registry):
        result = run(registry.execute("config", {"action": "doctor"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "config[doctor]")

    def test_get_missing_module(self, registry):
        result = run(registry.execute("config", {"action": "get"}))
        assert_expected_error(result, "config[get no module]")

    def test_get_unknown_module(self, registry):
        result = run(registry.execute("config", {
            "action": "get", "module": "nonexistent_module"
        }))
        assert_expected_error(result, "config[get unknown module]")

    def test_set_missing_params(self, registry):
        result = run(registry.execute("config", {
            "action": "set", "module": "llm"
        }))
        assert_expected_error(result, "config[set no path]")

    def test_resource_approve_missing_id(self, registry):
        result = run(registry.execute("config", {"action": "resource_approve"}))
        assert_expected_error(result, "config[resource_approve no id]", contains="resource_id")

    def test_role_get_missing_id(self, registry):
        result = run(registry.execute("config", {"action": "role_get"}))
        assert_expected_error(result, "config[role_get no id]", contains="module")

    def test_role_tools_not_placeholder(self, registry):
        result = run(registry.execute("role_design_start", {}))
        assert_no_crash(result)
        assert_not_placeholder(result, "role_design_start")

        session_id = result.get("session_id")
        assert session_id, "role_design_start should return session_id"

        result = run(registry.execute("role_design_answer", {
            "session_id": session_id,
            "answer": "TestRole is a concise research helper."
        }))
        assert_no_crash(result)
        assert_not_placeholder(result, "role_design_answer")

    def test_llm_models_missing_id(self, registry):
        result = run(registry.execute("config", {"action": "llm_models"}))
        assert_expected_error(result, "config[llm_models no id]", contains="resource_id")


# ---------------------------------------------------------------------------
# 9. scheduler hub
# ---------------------------------------------------------------------------

class TestSchedulerHub:
    def test_help_menu(self, registry):
        result = run(registry.execute("scheduler", {}))
        assert_help_menu(result, "scheduler", expected_actions=[
            "add", "list", "get", "remove", "purge", "status",
            "daemon_start", "daemon_stop", "daemon_restart", "list_tools",
        ])

    def test_status(self, registry):
        result = run(registry.execute("scheduler", {"action": "status"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "scheduler[status]")

    def test_list(self, registry):
        result = run(registry.execute("scheduler", {"action": "list"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "scheduler[list]")

    def test_list_tools(self, registry):
        result = run(registry.execute("scheduler", {"action": "list_tools"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "scheduler[list_tools]")

    def test_get_missing_task_id(self, registry):
        result = run(registry.execute("scheduler", {"action": "get"}))
        assert_expected_error(result, "scheduler[get no task_id]", contains="task_id")

    def test_remove_missing_task_id(self, registry):
        result = run(registry.execute("scheduler", {"action": "remove"}))
        assert_expected_error(result, "scheduler[remove no task_id]", contains="task_id")

    def test_unknown_action(self, registry):
        result = run(registry.execute("scheduler", {"action": "bad_action"}))
        assert_no_crash(result)
        assert "actions" in result
        assert "error" in result


# ---------------------------------------------------------------------------
# 10. dream hub
# ---------------------------------------------------------------------------

class TestDreamHub:
    def test_help_menu(self, registry):
        result = run(registry.execute("dream", {}))
        assert_help_menu(result, "dream", expected_actions=[
            "process", "list", "get", "upgrade",
        ])

    def test_list(self, registry):
        result = run(registry.execute("dream", {"action": "list"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "dream[list]")

    def test_process_missing_id(self, registry):
        result = run(registry.execute("dream", {"action": "process"}))
        assert_expected_error(result, "dream[process no id]", contains="conversation_id")

    def test_get_missing_id(self, registry):
        result = run(registry.execute("dream", {"action": "get"}))
        assert_expected_error(result, "dream[get no id]", contains="conversation_id")

    def test_upgrade_missing_params(self, registry):
        result = run(registry.execute("dream", {"action": "upgrade", "conversation_id": "x"}))
        assert_expected_error(result, "dream[upgrade no target]", contains="target_quality")

    def test_unknown_action(self, registry):
        result = run(registry.execute("dream", {"action": "bad_action"}))
        assert_no_crash(result)
        assert "actions" in result
        assert "error" in result


# ---------------------------------------------------------------------------
# 11. agent hub
# ---------------------------------------------------------------------------

class TestAgentHub:
    def test_help_menu(self, registry):
        result = run(registry.execute("agent", {}))
        assert_help_menu(result, "agent", expected_actions=[
            "list_types", "start", "stop", "status", "list",
            "restart", "destroy", "action",
        ])

    def test_list_types(self, registry):
        result = run(registry.execute("agent", {"action": "list_types"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "agent[list_types]")

    def test_list(self, registry):
        result = run(registry.execute("agent", {"action": "list"}))
        assert_no_crash(result)
        assert_not_placeholder(result, "agent[list]")

    def test_stop_missing_id(self, registry):
        result = run(registry.execute("agent", {"action": "stop"}))
        assert_expected_error(result, "agent[stop no id]", contains="agent_id")

    def test_status_missing_id(self, registry):
        result = run(registry.execute("agent", {"action": "status"}))
        assert_expected_error(result, "agent[status no id]", contains="agent_id")

    def test_unknown_action(self, registry):
        result = run(registry.execute("agent", {"action": "bad_action"}))
        assert_no_crash(result)
        assert "actions" in result
        assert "error" in result


# ---------------------------------------------------------------------------
# 12. external_agent hub
# ---------------------------------------------------------------------------

class TestExternalAgentHub:
    def test_help_menu(self, registry):
        result = run(registry.execute("external_agent", {}))
        assert_help_menu(result, "external_agent", expected_actions=["google"])

    def test_google_missing_params(self, registry):
        result = run(registry.execute("external_agent", {"action": "google"}))
        assert_expected_error(result, "external_agent[google no params]")

    def test_google_missing_method(self, registry):
        result = run(registry.execute("external_agent", {
            "action": "google", "service": "calendar", "resource": "events"
        }))
        assert_expected_error(result, "external_agent[google no method]", contains="method")

    def test_unknown_action(self, registry):
        result = run(registry.execute("external_agent", {"action": "bad_action"}))
        assert_no_crash(result)
        assert "actions" in result
        assert "error" in result


# ---------------------------------------------------------------------------
# Placeholder tools — must NOT be callable
# ---------------------------------------------------------------------------

class TestPlaceholderTools:
    RETIRED = [
        "get_memory_context", "get_current_day", "get_current_time",
        "get_recent_events", "get_attention_summary",
        "scheduler_resume_task", "get_memory_stats",
        "web_search",
        "end_conversation", "toggle_multi_model",
        "list_recent_conversations", "remove_conversation_message",
        "add_documents", "list_recent_documents", "remove_document",
        "knowledge_add_repo", "knowledge_list_repos",
        "scheduler_add_task", "scheduler_list_tasks", "scheduler_get_status",
        "dreaming_process", "dreaming_list_archives",
        "config_doctor", "resource_pool_status",
        "google_service",
    ]

    @pytest.mark.parametrize("tool_name", RETIRED)
    def test_retired_tool_is_placeholder(self, registry, tool_name):
        result = run(registry.execute(tool_name, {}))
        assert result.get("status") == "placeholder", (
            f"Retired tool '{tool_name}' should return placeholder but got: {result}"
        )


# ---------------------------------------------------------------------------
# Visible tool count sanity check
# ---------------------------------------------------------------------------

class TestToolSurface:
    EXPECTED_VISIBLE = {
        "get_context", "search_memory", "add_conversation", "reply_to_task",
        "task_session_read", "task_report_read",
        "memory", "knowledge", "config", "scheduler",
        "dream", "agent", "external_agent",
    }

    def test_visible_tool_count(self, registry):
        visible = {t["name"] for t in registry.get_tools()}
        missing = self.EXPECTED_VISIBLE - visible
        assert not missing, f"Expected visible tools are missing: {missing}"

    def test_no_retired_tools_visible(self, registry):
        visible = {t["name"] for t in registry.get_tools()}
        retired = set(TestPlaceholderTools.RETIRED)
        leaked = visible & retired
        assert not leaked, f"Retired tools are still visible in tool surface: {leaked}"

    def test_scheduler_description_teaches_capability_translation(self, registry):
        scheduler = next(t for t in registry.get_tools() if t["name"] == "scheduler")
        desc = scheduler["description"]
        available = scheduler["inputSchema"]["properties"]["available_tools"]["description"]

        assert "DISPATCHING A ROLE TASK" in desc
        assert "~/.memory/task_sessions/<task_id>.json" in desc
        assert "~/.memory/task_reports/<task_id>.json" in desc
        assert "category names" in available
        assert "exact tool names" in available
        assert "role's saved capabilities are used" in available
