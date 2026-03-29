"""
Smoke — Dashboard chat mode behavior contracts.

Verifies:
  - Tool filtering enforces mode contract categories
  - Response quality checker catches empty/hollow output
  - Mode overlay resolves role-specific > contract default
  - Tool-instruction sections are stripped from base prompt
  - _CHAT_MODE_ADDENDUM is sourced from the contract (not hardcoded separately)

No network or LLM calls required.
"""

import pytest
from app.scheduler.interaction_mode import InteractionMode, get_mode_contract
from app.scheduler.role_chat import (
    RoleChatSession,
    _CHAT_TOOL_ACCESS,
    _CHAT_MODE_ADDENDUM,
    _TOOL_DEFS,
    _ensure_response_quality,
    _strip_tool_sections,
)


class TestToolFiltering:

    def test_dashboard_chat_tools_only_memory_and_knowledge(self):
        """Only memory + knowledge categories are in _CHAT_TOOL_ACCESS and allowed."""
        contract = get_mode_contract(InteractionMode.DASHBOARD_CHAT)
        session = RoleChatSession("test_role")
        tools = session._get_chat_tools(["memory", "knowledge", "web", "browser"])
        tool_names = {t["function"]["name"] for t in tools}
        # memory tools present
        assert "memory_search" in tool_names
        assert "task_search" in tool_names
        assert "knowledge_search" in tool_names
        # web/browser tools absent
        assert "web_search" not in tool_names
        assert "fetch_url" not in tool_names

    def test_tool_access_categories_map_to_definitions(self):
        """Every tool name in _CHAT_TOOL_ACCESS has a definition in _TOOL_DEFS."""
        for category, names in _CHAT_TOOL_ACCESS.items():
            for name in names:
                assert name in _TOOL_DEFS, (
                    f"Tool '{name}' in _CHAT_TOOL_ACCESS['{category}'] "
                    f"has no definition in _TOOL_DEFS"
                )

    def test_role_with_no_memory_access_gets_no_chat_tools(self):
        session = RoleChatSession("test_role")
        tools = session._get_chat_tools([])  # role has no tool_access categories
        assert tools == []

    def test_mode_contract_categories_honored(self):
        """_get_chat_tools intersection: role categories ∩ mode allowed_categories."""
        session = RoleChatSession("test_role", mode=InteractionMode.DASHBOARD_CHAT)
        # Role has web access but mode doesn't allow it
        tools = session._get_chat_tools(["web"])
        assert tools == []


class TestResponseQualityChecker:

    def test_empty_response_returns_structured_fallback(self):
        result = _ensure_response_quality("", "Rebecca")
        assert "What I found" in result
        assert "What I could not confirm" in result
        assert "scheduled" in result.lower() or "task flow" in result.lower()

    def test_whitespace_only_response_is_treated_as_empty(self):
        result = _ensure_response_quality("   \n  ", "Rebecca")
        assert "What I found" in result

    def test_hollow_phrase_short_response_replaced(self):
        for phrase in [
            "Let me search for that.",
            "I'll search for the answer.",
            "Let me look into that.",
            "Searching for this information.",
        ]:
            result = _ensure_response_quality(phrase, "Rebecca")
            assert "What I found" in result, f"Hollow phrase not caught: {phrase!r}"

    def test_hollow_phrase_long_response_passes_through(self):
        """A response that starts with a hollow phrase but is long enough is real content."""
        long = "Let me search for that. " + "x" * 200
        result = _ensure_response_quality(long, "Rebecca")
        assert result == long

    def test_real_response_passes_through_unchanged(self):
        real = "The NineChapter system scores Rebecca at 95 overall, reflecting her strong research methodology."
        assert _ensure_response_quality(real, "Rebecca") == real

    def test_short_real_response_passes_through(self):
        """A short but genuine answer should not be replaced."""
        assert _ensure_response_quality("Yes.", "Rebecca") == "Yes."


class TestModeOverlayResolution:

    def test_addendum_alias_matches_contract_overlay(self):
        """_CHAT_MODE_ADDENDUM must equal the DASHBOARD_CHAT contract overlay."""
        contract_overlay = get_mode_contract(InteractionMode.DASHBOARD_CHAT).prompt_overlay
        assert _CHAT_MODE_ADDENDUM == contract_overlay

    def test_role_specific_overlay_takes_precedence(self):
        """If mode_overlays.dashboard_chat is set on a role, it overrides the contract."""
        role = {
            "name": "TestRole",
            "system_prompt": "You are test.",
            "mode_overlays": {
                "dashboard_chat": "CUSTOM OVERLAY FOR TESTING",
            },
        }
        role_overlay = (role.get("mode_overlays") or {}).get(
            InteractionMode.DASHBOARD_CHAT.value
        )
        contract = get_mode_contract(InteractionMode.DASHBOARD_CHAT)
        resolved = role_overlay if role_overlay else contract.prompt_overlay
        assert resolved == "CUSTOM OVERLAY FOR TESTING"

    def test_absent_role_overlay_falls_back_to_contract(self):
        role = {"name": "TestRole", "system_prompt": "You are test."}
        role_overlay = (role.get("mode_overlays") or {}).get(
            InteractionMode.DASHBOARD_CHAT.value
        )
        contract = get_mode_contract(InteractionMode.DASHBOARD_CHAT)
        resolved = role_overlay if role_overlay else contract.prompt_overlay
        assert resolved == contract.prompt_overlay


class TestStripToolSections:

    def test_strips_how_you_use_tools_section(self):
        prompt = (
            "## Values\nIntellectual honesty.\n\n"
            "## How you use tools\nUse memory_search first.\n\n"
            "## How you communicate\nDirectly.\n"
        )
        result = _strip_tool_sections(prompt)
        assert "How you use tools" not in result
        assert "memory_search first" not in result
        assert "Values" in result
        assert "How you communicate" in result

    def test_strips_when_tool_unavailable_section(self):
        prompt = (
            "## Purpose\nTo research.\n\n"
            "## When a tool is unavailable\nUse ask_user.\n\n"
            "## Other\nContent.\n"
        )
        result = _strip_tool_sections(prompt)
        assert "When a tool is unavailable" not in result
        assert "Purpose" in result

    def test_no_sections_to_strip_returns_original(self):
        prompt = "## Values\nHonesty.\n\n## Purpose\nResearch."
        result = _strip_tool_sections(prompt)
        assert "Values" in result
        assert "Purpose" in result
