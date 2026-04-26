"""
Interaction Mode contracts for MoJoAssistant.

Each mode is a first-class interaction surface with an explicit contract:
  - which tool categories are allowed
  - what prompt overlay is injected at the top of the system prompt
  - whether completed tasks should write a reviewable artifact

Modes
-----
DASHBOARD_CHAT          Private, read-only debrief (memory + task history only).
ROLE_CHAT               Same defaults as dashboard_chat unless mode_overlays expands it.
SCHEDULER_AGENTIC_TASK  Full execution surface — planning, tools, orchestration.
DIRECT_MCP_COMMAND      Operator/admin control path via authorized MCP channels.

Usage
-----
    from app.scheduler.interaction_mode import InteractionMode, get_mode_contract

    contract = get_mode_contract(InteractionMode.DASHBOARD_CHAT)
    system_prompt = contract.prompt_overlay + role_persona_prompt
"""
# [hitl-orchestrator: generic]
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class InteractionMode(str, Enum):
    DASHBOARD_CHAT = "dashboard_chat"
    ROLE_CHAT = "role_chat"
    SCHEDULER_AGENTIC_TASK = "scheduler_agentic_task"
    DIRECT_MCP_COMMAND = "direct_mcp_command"


@dataclass
class ModeContract:
    mode: InteractionMode
    # Tool catalog categories permitted in this mode.
    # role_chat.py maps these categories → concrete tool names.
    allowed_tool_categories: List[str]
    # Text prepended to the role's system prompt when this mode is active.
    # Empty string means no overlay (e.g. direct MCP commands rely on caller context).
    prompt_overlay: str
    # Whether a completed task should write a reviewable artifact to
    # ~/.memory/task_reports/{task_id}.json.
    # In task_report_v2, execution outcome lives in `status` while the
    # review workflow state lives in `review_status` (initially pending_review).
    stores_completion_artifact: bool = False


# ---------------------------------------------------------------------------
# Overlay text
# ---------------------------------------------------------------------------

_DASHBOARD_CHAT_OVERLAY = """\
## DASHBOARD CHAT — READ-ONLY DEBRIEF MODE

You are in a Dashboard Chat session. This is a private recall and debrief \
interface — NOT an agentic research session.

**The ONLY tools available to you right now are:**
- `memory_search` — search your memory and past conversations
- `task_search` — search your task history
- `knowledge_search` — search prior research reports and task completion artifacts

**These tools DO NOT EXIST in this session and must NOT be called:**
- `web_search`, `fetch_url`, any browser or Playwright tool
- Any orchestration, scheduling, or sub-agent tool
- Any write or execution tool

Do not generate tool call XML or JSON for unavailable tools. If you find \
yourself about to call `web_search` or any browser tool — stop. Use \
`memory_search`, `task_search`, or `knowledge_search` instead, or answer \
from what you already know.

When your search finds nothing useful or you cannot fully answer, use \
this exact structure — never return empty output or hollow phrases like \
"Let me search more" or "I'll look into that":

**What I found:** [any partial findings, or "nothing in my current memory on this topic"]
**What I could not confirm:** [what is missing or uncertain]
**To investigate further:** Route this as a scheduled research task through MoJo's task flow.

---
"""

_SCHEDULER_AGENTIC_OVERLAY = """\
## EXECUTION MODE — SCHEDULER AGENTIC TASK

You are running as an autonomous scheduled task on the full execution surface. \
Planning, tool use, and iterative research are all available within your \
granted tool set. Operate under lifecycle governance: use tools methodically, \
surface genuine blockers via ask_user, and produce a complete \
<FINAL_ANSWER> only when the goal is fully addressed.

---
"""


# ---------------------------------------------------------------------------
# Mode contracts
# ---------------------------------------------------------------------------

_MODE_CONTRACTS: dict[InteractionMode, ModeContract] = {
    InteractionMode.DASHBOARD_CHAT: ModeContract(
        mode=InteractionMode.DASHBOARD_CHAT,
        allowed_tool_categories=["memory", "knowledge"],
        prompt_overlay=_DASHBOARD_CHAT_OVERLAY,
        stores_completion_artifact=False,
    ),
    InteractionMode.ROLE_CHAT: ModeContract(
        mode=InteractionMode.ROLE_CHAT,
        allowed_tool_categories=["memory", "knowledge"],
        prompt_overlay=_DASHBOARD_CHAT_OVERLAY,  # same default as dashboard_chat
        stores_completion_artifact=False,
    ),
    InteractionMode.SCHEDULER_AGENTIC_TASK: ModeContract(
        mode=InteractionMode.SCHEDULER_AGENTIC_TASK,
        allowed_tool_categories=["memory", "web", "browser", "code", "file"],
        prompt_overlay=_SCHEDULER_AGENTIC_OVERLAY,
        stores_completion_artifact=True,
    ),
    InteractionMode.DIRECT_MCP_COMMAND: ModeContract(
        mode=InteractionMode.DIRECT_MCP_COMMAND,
        allowed_tool_categories=["memory", "web", "browser", "code", "file", "system"],
        prompt_overlay="",
        stores_completion_artifact=False,
    ),
}


def get_mode_contract(mode: InteractionMode) -> ModeContract:
    """Return the ModeContract for the given InteractionMode."""
    return _MODE_CONTRACTS[mode]
