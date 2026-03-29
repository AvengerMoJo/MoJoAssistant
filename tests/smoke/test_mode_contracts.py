"""
Smoke — InteractionMode contract structure and consistency.

Verifies that mode contracts are complete, internally consistent, and
that the DASHBOARD_CHAT contract explicitly forbids the right tools.
No network or LLM calls required.
"""

import pytest
from app.scheduler.interaction_mode import InteractionMode, ModeContract, get_mode_contract


class TestModeContractCompleteness:

    def test_all_modes_have_contracts(self):
        """Every InteractionMode enum value has a registered contract."""
        for mode in InteractionMode:
            contract = get_mode_contract(mode)
            assert isinstance(contract, ModeContract)
            assert contract.mode == mode

    def test_dashboard_chat_allows_only_read_categories(self):
        c = get_mode_contract(InteractionMode.DASHBOARD_CHAT)
        allowed = set(c.allowed_tool_categories)
        assert "memory" in allowed
        assert "knowledge" in allowed
        # Write/execution categories must not appear
        for forbidden in ("web", "browser", "exec", "orchestration", "file"):
            assert forbidden not in allowed, f"DASHBOARD_CHAT should not allow '{forbidden}'"

    def test_role_chat_same_defaults_as_dashboard(self):
        dc = get_mode_contract(InteractionMode.DASHBOARD_CHAT)
        rc = get_mode_contract(InteractionMode.ROLE_CHAT)
        assert dc.allowed_tool_categories == rc.allowed_tool_categories

    def test_scheduler_agentic_stores_artifact(self):
        c = get_mode_contract(InteractionMode.SCHEDULER_AGENTIC_TASK)
        assert c.stores_completion_artifact is True

    def test_dashboard_does_not_store_artifact(self):
        c = get_mode_contract(InteractionMode.DASHBOARD_CHAT)
        assert c.stores_completion_artifact is False

    def test_scheduler_agentic_allows_full_tool_set(self):
        c = get_mode_contract(InteractionMode.SCHEDULER_AGENTIC_TASK)
        for expected in ("memory", "web", "browser"):
            assert expected in c.allowed_tool_categories

    def test_direct_mcp_is_widest(self):
        """DIRECT_MCP_COMMAND should allow at least as many categories as agentic."""
        agentic = set(get_mode_contract(InteractionMode.SCHEDULER_AGENTIC_TASK).allowed_tool_categories)
        mcp = set(get_mode_contract(InteractionMode.DIRECT_MCP_COMMAND).allowed_tool_categories)
        assert agentic.issubset(mcp)


class TestDashboardChatOverlay:

    def test_overlay_names_available_tools(self):
        overlay = get_mode_contract(InteractionMode.DASHBOARD_CHAT).prompt_overlay
        assert "memory_search" in overlay
        assert "task_search" in overlay
        assert "knowledge_search" in overlay

    def test_overlay_forbids_web_tools(self):
        overlay = get_mode_contract(InteractionMode.DASHBOARD_CHAT).prompt_overlay
        assert "web_search" in overlay
        assert "fetch_url" in overlay

    def test_overlay_has_blocked_response_template(self):
        overlay = get_mode_contract(InteractionMode.DASHBOARD_CHAT).prompt_overlay
        assert "What I found" in overlay
        assert "What I could not confirm" in overlay
        assert "scheduled" in overlay.lower() or "task flow" in overlay.lower()

    def test_scheduler_agentic_overlay_nonempty(self):
        overlay = get_mode_contract(InteractionMode.SCHEDULER_AGENTIC_TASK).prompt_overlay
        assert len(overlay.strip()) > 0

    def test_direct_mcp_overlay_empty(self):
        """DIRECT_MCP_COMMAND needs no overlay — caller provides context."""
        overlay = get_mode_contract(InteractionMode.DIRECT_MCP_COMMAND).prompt_overlay
        assert overlay == ""
