"""
Agentic Executor

Autonomous think-act loop that drives LLM conversations to completion
using resources from the ResourceManager.
"""

import asyncio
import inspect
import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.scheduler.models import Task, TaskResult
from app.scheduler.resource_pool import LLMResource, ResourceManager, ResourceTier
from app.scheduler.session_storage import SessionMessage, SessionStorage, TaskSession
from app.scheduler.planning_prompt_manager import PlanningPromptManager
from app.scheduler.capability_registry import CapabilityRegistry
from app.scheduler.safety_policy import SafetyPolicy
from app.scheduler.security_gate import SecurityGate, Decision as SecurityDecision
from app.scheduler.interaction_mode import InteractionMode, get_mode_contract
from app.roles.owner_context import load_owner_profile, infer_context_tier, build_owner_context_slice
from app.scheduler.capability_resolver import CapabilityResolver
from app.scheduler.role_template_engine import RoleTemplateEngine
from app.scheduler.capability_gap_checker import CapabilityGapChecker

# Tools whose output commonly bloats context (bash stdout, file reads).
# Results longer than this cap are truncated before being added to messages.
_TOOL_OUTPUT_CAP_CHARS = 4000
_TOOL_OUTPUT_LARGE_TOOLS = {"bash_exec", "read_file", "file_read", "list_files", "search_in_files"}


def _estimate_tokens(messages: List[Dict]) -> int:
    """Fast token estimate: ~4 chars per token + 10 overhead per message."""
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        total += len(str(content)) // 4 + 10
        for tc in m.get("tool_calls", []):
            total += len(json.dumps(tc)) // 4 + 5
    return total


def _trim_to_context_budget(
    messages: List[Dict],
    input_budget: int,
) -> tuple:
    """Trim middle messages until estimated tokens fit within input_budget.

    Protected: system prompt (index 0), first user/goal message (index 1),
    and the last 4 messages. Everything in between is dropped oldest-first.

    Returns (trimmed_messages, was_trimmed).
    """
    if _estimate_tokens(messages) <= input_budget:
        return messages, False

    protected_head = messages[:2]
    protected_tail = messages[-4:] if len(messages) > 6 else messages[2:]
    trimmable = messages[2: len(messages) - 4] if len(messages) > 6 else []

    while trimmable and _estimate_tokens(protected_head + trimmable + protected_tail) > input_budget:
        trimmable.pop(0)

    return protected_head + trimmable + protected_tail, True


def _parse_final_answer_sections(text: str) -> Dict[str, Any]:
    """
    Extract structured sections from a FINAL_ANSWER that follows the contract:
      **Completed:** bullet list
      **Findings:** bullet list
      **Incomplete:** bullet list
      **Resume hint:** single line or bullet list

    Returns a dict with keys: completed, findings, incomplete, resume_hint.
    Any missing section is an empty list (or empty string for resume_hint).
    """
    section_keys = {
        "completed": re.compile(r"\*\*Completed[:\*]*\*\*", re.IGNORECASE),
        "findings": re.compile(r"\*\*Findings[:\*]*\*\*", re.IGNORECASE),
        "incomplete": re.compile(r"\*\*Incomplete[:\*]*\*\*", re.IGNORECASE),
        "resume_hint": re.compile(r"\*\*Resume hint[:\*]*\*\*", re.IGNORECASE),
    }
    ordered = ["completed", "findings", "incomplete", "resume_hint"]

    # Find start/end positions of each section header
    # positions[key] = (header_start, header_end) — content begins at header_end,
    # and the block for key ends at header_start of the next section.
    positions: Dict[str, tuple] = {}
    for key, pattern in section_keys.items():
        m = pattern.search(text)
        if m:
            positions[key] = (m.start(), m.end())

    result: Dict[str, Any] = {k: [] for k in ordered}
    result["resume_hint"] = ""

    for i, key in enumerate(ordered):
        if key not in positions:
            continue
        _hdr_start, content_start = positions[key]
        # End = START of the next section header (not its end), so the header
        # text of the next section is never included in this block.
        end = len(text)
        for other in ordered[i + 1:]:
            if other in positions and positions[other][0] > content_start:
                end = min(end, positions[other][0])
                break
        block = text[content_start:end].strip()
        if key == "resume_hint":
            # Single value — strip bullet marker if present
            result["resume_hint"] = re.sub(r"^[-*•]\s*", "", block.split("\n")[0]).strip()
        else:
            bullets = []
            for line in block.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Accept bullet-prefixed lines (-, *, •, digit+dot)
                if re.match(r"^[-•]|^\d+\.", line):
                    bullets.append(re.sub(r"^[-•\d.]\s*", "", line).strip())
                elif not line.startswith("*"):
                    # Paragraph-style line (no bullet prefix, not a markdown bold marker)
                    bullets.append(line)
            result[key] = bullets

    return result


DEFAULT_SYSTEM_PROMPT = """\
You are an autonomous assistant running as a scheduled task. Your owner can help \
if you hit a blocker you cannot resolve on your own.

Think step by step. When you have completed the goal, wrap your final answer in \
<FINAL_ANSWER> tags like this:

<FINAL_ANSWER>
Your complete answer here.
</FINAL_ANSWER>

If you need more steps to reach the answer, continue reasoning. \
Do not use FINAL_ANSWER until you are confident the goal is fully addressed.

You may have tools available. Use them when needed to gather information.

If you encounter an unresolvable blocker — a required tool is unavailable, you need \
information only the owner has, or a decision requires human judgment — use ask_user \
to surface it. Do NOT use ask_user to report progress; only use it when genuinely stuck."""

# Tool definitions for the agentic loop - dynamically loaded from registry
BUILTIN_TOOLS = {
    "memory_search": {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search the user's memory (conversations, documents, knowledge base) for relevant context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant context",
                    },
                },
                "required": ["query"],
            },
        },
    },
    "ask_user": {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Pause the task and surface a blocker to the owner (user). "
                "Use this when you cannot proceed without human help: a required tool is unavailable, "
                "you need information only the owner has, or a decision requires human judgment. "
                "Do NOT use this to report progress or status — only when genuinely blocked."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The specific question or blocker to surface to the owner",
                    },
                },
                "required": ["question"],
            },
        },
    },
    # Individual browser tools — Qwen handles one-tool-one-action better than enum dispatch.
    # These all route through _execute_browser_facade which calls the playwright MCP server.
    "browser_navigate": {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Open a URL in the headless browser. Call before any page interactions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to navigate to."},
                },
                "required": ["url"],
            },
        },
    },
    "browser_snapshot": {
        "type": "function",
        "function": {
            "name": "browser_snapshot",
            "description": (
                "Get an accessibility snapshot of the current page — text content, "
                "element roles, and refs. Use this BEFORE clicking or typing to find "
                "the correct selector/ref for the target element."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    "browser_screenshot": {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "Take a visual screenshot of the current page. Use to verify page state visually.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    "browser_click": {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": (
                "Click an element on the page. "
                "Use the 'ref' value from browser_snapshot output (e.g. ref='e21'). "
                "Also provide 'element' as a short human description of what you're clicking."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ref":     {"type": "string", "description": "Element ref from browser_snapshot (e.g. 'e21')."},
                    "element": {"type": "string", "description": "Human description of the element (e.g. 'Login button')."},
                },
                "required": ["ref"],
            },
        },
    },
    "browser_type": {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": (
                "Type text into an input field. "
                "Use the 'ref' value from browser_snapshot output (e.g. ref='e16'). "
                "Also provide 'element' as a short human description of the field."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ref":     {"type": "string", "description": "Element ref from browser_snapshot (e.g. 'e16')."},
                    "element": {"type": "string", "description": "Human description of the input (e.g. 'Username field')."},
                    "text":    {"type": "string", "description": "Text to type into the field."},
                },
                "required": ["ref", "text"],
            },
        },
    },
    "browser_press_key": {
        "type": "function",
        "function": {
            "name": "browser_press_key",
            "description": "Press a keyboard key (e.g. Enter to submit a form, Tab to move focus, Escape to dismiss).",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key name: 'Enter', 'Tab', 'Escape', 'Space', etc."},
                },
                "required": ["key"],
            },
        },
    },
    "google_calendar_list": {
        "type": "function",
        "function": {
            "name": "google_calendar_list",
            "description": (
                "List events from Google Calendar for a given date range. "
                "Use to check Alex's schedule for today, this week, or any date range. "
                "Returns event titles, start/end times, and descriptions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start of date range. ISO date or datetime, e.g. '2026-04-02' or '2026-04-02T00:00:00'.",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End of date range (exclusive). ISO date or datetime, e.g. '2026-04-09'.",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar to read from. Default: 'primary' (Alex's main calendar).",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of events to return. Default: 20.",
                    },
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    "google_calendar_create": {
        "type": "function",
        "function": {
            "name": "google_calendar_create",
            "description": (
                "Create a new event on Google Calendar. "
                "Only use for the ops calendar (MoJo operational tasks) unless Alex explicitly "
                "asks for an event on his primary calendar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title/summary."},
                    "start_at": {"type": "string", "description": "Event start as ISO datetime, e.g. '2026-04-03T10:00:00'."},
                    "end_at": {"type": "string", "description": "Event end as ISO datetime. Optional — uses duration_minutes if absent."},
                    "details": {"type": "string", "description": "Event description or notes."},
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar to write to. Default: 'primary'. Use 'mojo_assistant_ops' for operational tasks.",
                    },
                    "timezone": {"type": "string", "description": "Timezone, e.g. 'Asia/Taipei'. Default: 'Asia/Taipei'."},
                    "duration_minutes": {"type": "integer", "description": "Duration in minutes if end_at not provided. Default: 30."},
                },
                "required": ["title", "start_at"],
            },
        },
    },
}

CONTINUE_PROMPT = (
    "Continue working toward the goal. "
    "If you are done, provide your answer inside <FINAL_ANSWER> tags."
)

NEAR_LIMIT_PROMPT = (
    "⚠ ITERATION BUDGET WARNING: You are on iteration {current} of {max} — only {remaining} iteration(s) left.\n\n"
    "Pick exactly one option:\n\n"
    "**Option A — Task is complete:** produce <FINAL_ANSWER> now.\n\n"
    "**Option B — Task is NOT complete:** write this exact text:\n"
    "  BUDGET_EXTENSION_REQUEST: Need N more iterations. Done: [what you finished]. Remaining: [what's left].\n"
    "  The system will grant more cycles automatically.\n\n"
    "Do NOT produce a partial FINAL_ANSWER if you are not done. Write Option B text instead."
)

_BUDGET_EXTENSION_PREFIX = "BUDGET_EXTENSION_REQUEST:"
_BUDGET_EXTENSION_MAX_GRANT = 20  # cap per extension to avoid runaway loops


class AgenticExecutor:
    """Executes agentic tasks via an autonomous LLM think-act loop."""

    def __init__(
        self,
        resource_manager: ResourceManager,
        logger: Optional[Any] = None,
        memory_service: Optional[Any] = None,
        mcp_client_manager: Optional[Any] = None,
        scheduler: Optional[Any] = None,
    ) -> None:
        self._rm = resource_manager
        self._logger = logger
        self._memory_service = memory_service
        self._session_storage = SessionStorage()
        self._planning_manager = PlanningPromptManager()
        self._tool_registry = CapabilityRegistry()
        self._tool_registry.set_memory_service(memory_service)
        from app.scheduler.mcp_client_manager import MCPClientManager
        self._mcp_client_manager = mcp_client_manager if mcp_client_manager is not None else MCPClientManager()
        self._tool_registry.set_mcp_client_manager(self._mcp_client_manager)
        if scheduler is not None:
            self._tool_registry.set_scheduler(scheduler)
        self._mcp_tools_discovered = False
        self._policy = SafetyPolicy()
        self._gate = SecurityGate(safety_policy=self._policy)
        self._capability_resolver = CapabilityResolver()
        self._role_template_engine = RoleTemplateEngine()
        self._gap_checker = CapabilityGapChecker()
        self._openrouter_model_cache: Dict[str, Dict[str, Any]] = {}
        self._openrouter_model_cache_ttl_seconds = 600
        self._role_id: Optional[str] = None

    def _log(self, message: str, level: str = "info"):
        if self._logger:
            getattr(self._logger, level)(f"[AgenticExecutor] {message}")

    def _record(self, task_id: str, role: str, content: str, iteration: int, **kwargs: Any) -> None:
        """Append a message to the session log."""
        self._session_storage.append_message(
            task_id,
            SessionMessage(
                role=role,
                content=content,
                timestamp=datetime.now().isoformat(),
                iteration=iteration,
                **kwargs,
            ),
        )

    async def execute(self, task: Task) -> TaskResult:
        """
        Run the agentic loop for a task.

        Task config keys:
            goal (str): What the agent should accomplish.
            system_prompt (str, optional): Override default system prompt.
            max_iterations (int, optional): Max LLM round-trips (default from resources).
            context (dict, optional): Extra context injected into first user message.
            max_duration_seconds (int, optional): Wall-clock time budget.
            tier_preference (list[str], optional): Resource tier preference.
            resume_from_task_id (str, optional): Load previous session and continue.
            reply_to_question (str, optional): User reply injected after WAITING_FOR_INPUT resume.
        """
        # Per-execution state for ask_user
        self._waiting_for_input_question: Optional[str] = None
        self._waiting_for_input_choices: Optional[list] = None
        self._gate_escalation_pending: bool = False  # True when pause was from SecurityGate
        self._tool_calls_made: int = 0          # non-ask_user tool calls this execution
        self._consecutive_no_tool: int = 0      # iterations with tools available but unused
        self._budget_extension_granted: int = 0  # extra iterations granted via BUDGET_EXTENSION_REQUEST
        self._exhausts_tools_before_asking: bool = False
        self._requires_tool_use: bool = False   # reject final answer if no tools called yet
        # Task id stored so _execute_single_tool can inject per-task tmux socket
        self._current_task_id: Optional[str] = task.id
        # Propagate task context to registry for sub-agent dispatch linkage + role scoping
        _task_role_id = (task.config or {}).get("role_id") if task.config else None
        self._tool_registry.set_task_context(task.id, task.dispatch_depth, role_id=_task_role_id)

        config = task.config or {}
        goal = config.get("goal", "")
        if not goal:
            return TaskResult(
                success=False, error_message="Missing 'goal' in task config"
            )

        # Load role personality if role_id is specified
        role_model_preference = None
        role_id = config.get("role_id")
        self._role_id = role_id  # make role_id available to tool dispatch
        from app.scheduler.policy_monitor import PolicyMonitor
        self._policy_monitor = PolicyMonitor(role_id=None, policy=None)
        if not role_id:
            self._log(
                f"DEPRECATION: assistant task {task.id} has no role_id. "
                "Assign a role via role_id — tasks without a role will be rejected in a future release.",
                level="warning",
            )
        self._data_boundary: dict = {}  # role-level data boundary constraints
        role = None  # populated below if role_id resolves
        if role_id:
            try:
                from app.roles.role_manager import RoleManager
                role = RoleManager().get(role_id)
                if role:
                    role_model_preference = role.get("model_preference")
                    self._policy_monitor = PolicyMonitor.from_role(role_id, role, task_id=task.id)
                    self._log(f"Loaded role: {role.get('name')} (id={role_id})")
                    behavior_rules = role.get("behavior_rules", {})
                    self._exhausts_tools_before_asking = behavior_rules.get(
                        "exhausts_tools_before_asking", False
                    )
                    self._requires_tool_use = behavior_rules.get(
                        "requires_tool_use", False
                    )
                    # Pull expanded data_boundary from monitor (local_only expansion applied)
                    self._data_boundary = self._policy_monitor.data_boundary
                else:
                    self._log(f"Role '{role_id}' not found — continuing without role")
            except Exception as e:
                self._log(f"Failed to load role '{role_id}': {e}")

        # Setup-time ceiling: validate available_tools against role policy
        available_tools = config.get("available_tools", [])
        if available_tools:
            violations = self._policy_monitor.validate_available_tools(available_tools)
            if violations:
                for v in violations:
                    self._log(f"Policy ceiling violation: {v}", "warning")

        # Load planning prompt — default to assistant_workflow when a role is active
        default_prompt = "assistant_workflow" if role_id else "agentic_planning"
        planning_prompt_name = config.get("planning_prompt", default_prompt)
        planning_prompt = self._planning_manager.get_prompt(
            planning_prompt_name, version="latest"
        )

        if planning_prompt:
            workflow_prompt = planning_prompt.content
            self._log(
                f"Using planning prompt: {planning_prompt_name} v{planning_prompt.version}"
            )
        else:
            if config.get("system_prompt") and not role_id:
                self._log(
                    f"DEPRECATION: task {task.id} uses inline system_prompt without role_id. "
                    "Create a role with role_create and pass role_id instead. "
                    "Inline system_prompt will be rejected in a future release.",
                    level="warning",
                )
            workflow_prompt = config.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
            self._log(
                f"Using default system prompt (no planning prompt found: {planning_prompt_name})"
            )

        # Combine: mode overlay + role personality + workflow instructions.
        # Mode overlay is role-specific if defined in mode_overlays, else contract default.
        mode_contract = get_mode_contract(InteractionMode.SCHEDULER_AGENTIC_TASK)
        role_overlay = (role.get("mode_overlays") or {}).get(
            InteractionMode.SCHEDULER_AGENTIC_TASK.value
        ) if role else None
        mode_overlay = role_overlay if role_overlay else mode_contract.prompt_overlay

        # Resolve tool names: system defaults + role capabilities + runtime override.
        enabled_tool_names = self._capability_resolver.resolve(
            role, config.get("available_tools"), self._tool_registry
        )
        self._enabled_tool_names = enabled_tool_names

        from datetime import datetime, timezone
        _now = datetime.now(timezone.utc).astimezone()
        runtime_context = (
            f"## Runtime context\n"
            f"- Current date and time: {_now.strftime('%Y-%m-%d %H:%M %Z')}\n\n"
        )

        character_block = self._role_template_engine.build(role) if role else ""
        if character_block:
            system_prompt = (
                mode_overlay
                + runtime_context
                + character_block
                + "\n\n---\n\n"
                + workflow_prompt
            )
        else:
            system_prompt = mode_overlay + runtime_context + workflow_prompt

        max_iterations = config.get("max_iterations", task.resources.max_iterations)
        max_duration = config.get(
            "max_duration_seconds",
            task.resources.max_duration_seconds or 300,
        )

        # Tier preference: task config > role resource_requirements > task resources > default
        role_resource_requirements = role.get("resource_requirements") if role else None
        tier_pref_raw = config.get("tier_preference", task.resources.tier_preference)
        if not tier_pref_raw and role_resource_requirements:
            tier_pref_raw = role_resource_requirements.get("tier")
        if tier_pref_raw:
            # Normalise: a bare string like "free" should become ["free"], not ["f","r","e","e"]
            if isinstance(tier_pref_raw, str):
                tier_pref_raw = [tier_pref_raw]
            tier_preference = [ResourceTier(t) for t in tier_pref_raw]
        else:
            tier_preference = [ResourceTier.FREE, ResourceTier.FREE_API]

        # Owner context — inject filtered slice based on whether we may call external LLMs.
        _owner_profile = load_owner_profile()
        if _owner_profile:
            _context_tier = infer_context_tier(tier_preference)
            _owner_slice = build_owner_context_slice(_owner_profile, _context_tier)
            if _owner_slice:
                system_prompt = system_prompt + _owner_slice
                self._log(f"Owner context injected (tier={_context_tier})")

        # Lazy-connect external MCP servers and register their tools on first use.
        if not self._mcp_tools_discovered and self._mcp_client_manager.has_servers():
            try:
                import asyncio
                count = await self._mcp_client_manager.discover_and_register(self._tool_registry)
                self._mcp_tools_discovered = True
                if count:
                    self._log(f"Registered {count} tools from external MCP servers")
            except Exception as e:
                self._log(f"External MCP discovery failed (continuing): {e}", level="warning")
                self._mcp_tools_discovered = True  # don't retry on every task

        # Tool names already resolved above (before capability_summary build).
        # self._enabled_tool_names is set; nothing to re-resolve here.
        tool_defs = []

        for tool_name in enabled_tool_names:
            # Check dynamic registry first
            tool = self._tool_registry.get_tool(tool_name)
            if tool:
                tool_defs.append(tool.to_openai_function())
            # Fallback to builtins
            elif tool_name in BUILTIN_TOOLS:
                tool_defs.append(BUILTIN_TOOLS[tool_name])

        # --- Capability gap check (fresh starts only) ---
        # Run before resume logic so we can bail early on missing-capability blockers.
        _gap_resume_skip = config.get("resume_from_task_id")
        if not _gap_resume_skip:
            gap_result = self._gap_checker.check(goal, enabled_tool_names, role)
            for w in gap_result.warnings:
                self._log(f"CapabilityGapChecker warning: {w}", "warning")
            if gap_result.has_blockers:
                self._log(
                    f"CapabilityGapChecker BLOCKER for task {task.id}: {gap_result.blockers}"
                )
                return TaskResult(
                    success=False,
                    waiting_for_input=gap_result.ask_user_question(),
                    waiting_for_input_choices=["add capabilities", "proceed anyway"],
                )

        # --- Resume support ---
        resume_from = config.get("resume_from_task_id")
        reply_to_question = config.pop("reply_to_question", None)
        # Reset SecurityGate danger budget only on fresh starts.
        # On resume (HITL reply or retry) the budget carries over so the gate
        # doesn't re-trigger immediately after the user says "continue".
        if not resume_from:
            self._gate.reset_task(task.id)
        if resume_from:
            messages, start_iteration = self._load_resume_messages(
                resume_from, system_prompt
            )
            if messages is None:
                return TaskResult(
                    success=False,
                    error_message=f"Cannot resume: session '{resume_from}' not found",
                )
            if reply_to_question:
                # If the pause was a SecurityGate budget escalation and the user approved,
                # grant a budget extension so the gate doesn't immediately re-fire.
                # Detection uses task.pending_question (persisted in the scheduler DB)
                # so it survives executor restarts — no in-memory flag needed.
                _pending_q = (task.pending_question or "").lower()
                _is_gate_escalation = "danger budget exhausted" in _pending_q
                _reply_lower = (reply_to_question or "").strip().lower()
                if _is_gate_escalation and _reply_lower in ("continue", "yes", "ok", "proceed", "go"):
                    self._gate.grant_override(task.id)
                    self._log(
                        f"User override granted for task {task.id} — gate budget extended"
                    )

                # Resume after WAITING_FOR_INPUT: inject the user's reply
                messages.append(
                    {
                        "role": "user",
                        "content": f"User's reply: {reply_to_question}",
                    }
                )
                self._record(
                    task.id, "user",
                    f"User's reply: {reply_to_question}",
                    iteration=start_iteration,
                )
            else:
                # Normal resume after timeout/failure
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The previous attempt ran out of time or failed. "
                            "Continue working toward the original goal. "
                            "If you are done, provide your answer inside <FINAL_ANSWER> tags."
                        ),
                    }
                )
        else:
            start_iteration = 0
            # Build initial messages
            messages: List[Dict[str, str]] = [
                {"role": "system", "content": system_prompt},
            ]
            # ORIENT: search memory for relevant past procedures/context before the loop
            orient_block = ""
            if not resume_from:
                orient_block = await self._orient_from_memory(goal, role_id)

            # Build first user message with goal + optional context + orientation
            user_content = f"Goal: {goal}"
            context = config.get("context")
            if context:
                user_content += (
                    f"\n\nContext:\n{json.dumps(context, indent=2, default=str)}"
                )
            if orient_block:
                user_content += orient_block
            messages.append({"role": "user", "content": user_content})

        # --- Create session ---
        session = TaskSession(
            task_id=task.id,
            status="running",
            messages=[],
            started_at=datetime.now().isoformat(),
            metadata={
                "goal": goal,
                "max_iterations": max_iterations,
                "resume_from": resume_from,
            },
        )
        self._session_storage.save_session(session)

        # Record initial messages
        for msg in messages:
            role = msg.get("role", msg.get("type", "unknown"))
            content = msg.get("content", "")
            if isinstance(content, dict):
                content = json.dumps(content, default=str)
            self._record(task.id, role, content or "", iteration=0)

        iteration_log: List[Dict[str, Any]] = []
        start_time = time.time()
        final_answer: Optional[str] = None
        auto_extracted: bool = False  # provenance flag for fallback completion
        _context_trim_count: int = 0
        _last_resource_id: Optional[str] = None
        _last_used_model: Optional[str] = None

        # Tracked across iterations for fallback completion recovery
        _last_response_text: str = ""
        _last_turn_had_tool_calls: bool = False

        self._log(
            f"Starting agentic loop for task {task.id} (max {max_iterations} iterations)"
        )

        iteration = 0
        while True:
            iteration += 1
            # Apply any budget extension granted by BUDGET_EXTENSION_REQUEST ask_user calls
            if self._budget_extension_granted > 0:
                max_iterations += self._budget_extension_granted
                self._log(
                    f"Task {task.id}: budget extended +{self._budget_extension_granted} "
                    f"iterations (new max: {max_iterations})"
                )
                self._budget_extension_granted = 0
            if iteration > max_iterations:
                break
            abs_iteration = start_iteration + iteration
            elapsed = time.time() - start_time
            if elapsed >= max_duration:
                self._log(
                    f"Task {task.id}: time budget exhausted at iteration {iteration}"
                )
                self._session_storage.update_status(
                    task.id,
                    "timed_out",
                    error_message="Time budget exhausted",
                )
                break

            # Acquire a resource (dynamic policy can reorder tiers per iteration)
            iter_tiers, selection_reason = self._determine_tier_preference_for_iteration(
                base_tiers=tier_preference,
                goal=goal,
                config=config,
                iteration_log=iteration_log,
            )
            pinned_resource_id = config.get("pinned_resource")
            if pinned_resource_id:
                resource = self._rm.acquire_by_id(pinned_resource_id)
                if resource is None:
                    self._log(f"Pinned resource '{pinned_resource_id}' unavailable, falling back to tier selection")
                    resource = self._rm.acquire(tier_preference=iter_tiers)
            elif role_resource_requirements:
                resource = self._rm.acquire_by_requirements(role_resource_requirements)
                if resource is None:
                    # Fall back to tier-only acquire if requirements can't be fully satisfied
                    resource = self._rm.acquire(tier_preference=iter_tiers)
            else:
                resource = self._rm.acquire(tier_preference=iter_tiers)
            if resource is None:
                self._log(f"No resource available, waiting 30s (iteration {iteration})")
                # Wait and retry once
                import asyncio

                await asyncio.sleep(30)
                resource = self._rm.acquire(tier_preference=iter_tiers)
                if resource is None:
                    self._log("Still no resource available, aborting")
                    iteration_log.append(
                        {
                            "iteration": iteration,
                            "status": "no_resource",
                            "tier_preference": [t.value for t in iter_tiers],
                            "selection_reason": selection_reason,
                            "elapsed_s": round(time.time() - start_time, 1),
                        }
                    )
                    break

            # Data boundary: enforce allowed_tiers constraint from role
            allowed_tiers = self._data_boundary.get("allowed_tiers")
            if allowed_tiers and resource.tier.value not in allowed_tiers:
                await self._emit_policy_violation(
                    task_id=task.id,
                    tool_name="<llm_resource>",
                    layer="data_boundary",
                    checker="data_boundary",
                    decision="block",
                    reason=(
                        f"Resource tier '{resource.tier.value}' is not permitted by this role "
                        f"(data_boundary.allowed_tiers={allowed_tiers})."
                    ),
                    severity="error",
                    metadata={"resource_tier": resource.tier.value, "allowed_tiers": allowed_tiers},
                )
                return TaskResult(
                    success=False,
                    error_message=(
                        f"Data boundary violation: resource tier '{resource.tier.value}' "
                        f"not in role's allowed_tiers {allowed_tiers}."
                    ),
                )

            # Context budget guard — trim history before it overflows the model window.
            _context_limit = getattr(resource, "context_limit", 32768)
            _output_limit  = getattr(resource, "output_limit", 8192)
            _input_limit   = getattr(resource, "input_limit", None)  # explicit cap if set
            _input_budget  = int((_input_limit or (_context_limit - _output_limit)) * 0.85)
            _estimated_tokens = _estimate_tokens(messages)
            messages, _was_trimmed = _trim_to_context_budget(messages, _input_budget)
            if _was_trimmed:
                _context_trim_count += 1
                self._log(
                    f"Context trim: ~{_estimated_tokens}t estimated, budget={_input_budget}t "
                    f"({_context_limit}t window). Oldest messages dropped.",
                    "warning",
                )

            # Call LLM
            effective_model = role_model_preference or resource.model
            self._log(
                f"Iteration {iteration}: calling {effective_model} via {resource.id} "
                f"(~{_estimate_tokens(messages)}t input)"
            )
            iter_start = time.time()
            try:
                response = await self._call_llm(
                    resource, messages, tools=tool_defs or None,
                    model_override=role_model_preference,
                )
                self._rm.record_usage(resource.id, success=True)
                # Audit trail — log every non-free external boundary crossing
                if resource.tier.value != "free":
                    try:
                        from app.mcp.adapters.audit_log import append as _audit_append
                        usage = response.get("usage") or {}
                        _audit_append(
                            task_id=task.id,
                            role_id=role_id,
                            resource_id=resource.id,
                            resource_type=resource.type,
                            tier=resource.tier.value,
                            model=response.get("_selected_model", resource.model),
                            tokens_in=usage.get("prompt_tokens", 0),
                            tokens_out=usage.get("completion_tokens", 0),
                            tokens_total=usage.get("total_tokens", 0),
                        )
                    except Exception:
                        pass  # audit logging must never break task execution
            except Exception as e:
                self._rm.record_usage(resource.id, success=False)
                self._log(f"LLM call failed: {e}", "error")
                iteration_log.append(
                    {
                        "iteration": iteration,
                        "resource": resource.id,
                        "status": "error",
                        "tier_preference": [t.value for t in iter_tiers],
                        "selection_reason": selection_reason,
                        "error": str(e) or type(e).__name__,
                        "elapsed_s": round(time.time() - iter_start, 1),
                    }
                )
                continue  # Try next iteration with potentially different resource

            message = response["choices"][0]["message"]
            used_model = response.get("_selected_model", resource.model)
            _last_resource_id = resource.id
            _last_used_model = used_model
            # Thinking models (e.g. Qwen3) return reasoning in reasoning_content
            # with content empty. Fall back so the executor can see the response.
            response_text = message.get("content", "") or message.get("reasoning_content", "") or ""
            # Strip <think>...</think> blocks in case llama.cpp didn't separate them
            # (older builds or non-jinja mode leak think tokens into content).
            response_text = re.sub(r"<think>.*?</think>", "", response_text, flags=re.DOTALL).strip()
            tool_calls = message.get("tool_calls")

            # Track last substantive assistant turn for fallback completion recovery
            _last_response_text = response_text
            _last_turn_had_tool_calls = bool(tool_calls)

            # Handle tool calls if present
            if tool_calls:
                self._consecutive_no_tool = 0  # reset drift counter on actual tool use
                # Append assistant message with tool calls
                messages.append(message)
                self._record(
                    task.id,
                    "assistant",
                    response_text,
                    iteration=abs_iteration,
                    metadata={
                        "tool_calls": [tc["function"]["name"] for tc in tool_calls]
                    },
                )

                tool_results = await self._execute_tool_calls(tool_calls)
                waiting = self._waiting_for_input_question
                for tc, result_content in zip(tool_calls, tool_results):
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_content,
                        }
                    )
                    self._record(
                        task.id,
                        "tool",
                        result_content,
                        iteration=abs_iteration,
                        tool_call_id=tc["id"],
                        tool_name=tc["function"]["name"],
                    )

                _tool_iter_entry: Dict[str, Any] = {
                    "iteration": iteration,
                    "resource": resource.id,
                    "model": used_model,
                    "tier_preference": [t.value for t in iter_tiers],
                    "selection_reason": selection_reason,
                    "status": "tool_use",
                    "tool_calls": [tc["function"]["name"] for tc in tool_calls],
                    "estimated_input_tokens": _estimated_tokens,
                    "elapsed_s": round(time.time() - iter_start, 1),
                }
                if _was_trimmed:
                    _tool_iter_entry["context_trimmed"] = True
                iteration_log.append(_tool_iter_entry)
                # If agent called ask_user, pause the loop here
                if waiting:
                    self._log(
                        f"Task {task.id}: pausing for user input — '{waiting[:80]}'"
                    )
                    break

                # If we're near the iteration limit, inject a hard wrap-up prompt
                # so the LLM doesn't keep calling tools and runs out of budget.
                if iteration >= max_iterations - 1:
                    remaining = max_iterations - iteration
                    budget_msg = NEAR_LIMIT_PROMPT.format(
                        current=iteration, max=max_iterations, remaining=remaining
                    )
                    messages.append({"role": "user", "content": budget_msg})
                    self._record(task.id, "user", budget_msg, iteration=abs_iteration)
                continue  # Next iteration will get the LLM's response to tool results

            # Append assistant response
            messages.append({"role": "assistant", "content": response_text})
            self._record(task.id, "assistant", response_text, iteration=abs_iteration)

            # Detect plain-text BUDGET_EXTENSION_REQUEST (agent wrote it as text, not a tool call)
            if _BUDGET_EXTENSION_PREFIX in response_text and self._budget_extension_granted == 0:
                import re as _re
                match = _re.search(r"Need\s+(\d+)\s+more", response_text, _re.IGNORECASE)
                grant = min(int(match.group(1)) if match else 10, _BUDGET_EXTENSION_MAX_GRANT)
                max_iterations += grant
                self._log(
                    f"Task {task.id}: plain-text budget extension detected, granted +{grant} "
                    f"(new max: {max_iterations})"
                )
                messages.append({"role": "user", "content": f"Budget extended by {grant} iterations. Continue your work."})
                self._record(task.id, "user", f"Budget extended by {grant} iterations. Continue your work.", iteration=abs_iteration)
                continue

            # Check for final answer
            candidate_final_answer = self._parse_final_answer(response_text)
            final_validation_error = None
            final_answer = None

            # behavior_rules.requires_tool_use: if the agent tries to submit a
            # final answer without having called any tools yet, reject it and
            # inject a targeted forcing message so the next iteration acts.
            if (
                candidate_final_answer is not None
                and self._requires_tool_use
                and self._tool_calls_made == 0
            ):
                forcing_msg = (
                    "Your plan is noted but you have not called any tools yet. "
                    "Do not write a final answer until you have used at least one tool. "
                    "Call a tool now to execute your plan."
                )
                messages.append({"role": "user", "content": forcing_msg})
                self._record(task.id, "user", forcing_msg, iteration=abs_iteration)
                self._log(f"Task {task.id}: requires_tool_use — forcing tool call at iteration {iteration}")
                iteration_log.append({
                    "iteration": iteration,
                    "resource": resource.id,
                    "model": used_model,
                    "tier_preference": [t.value for t in iter_tiers],
                    "selection_reason": selection_reason,
                    "status": "forced_tool_use",
                    "response_length": len(response_text),
                    "validation_error": None,
                    "elapsed_s": round(time.time() - iter_start, 1),
                })
                continue

            if candidate_final_answer is not None:
                is_valid, validation_error = self._validate_final_answer(
                    final_answer=candidate_final_answer,
                    goal=goal,
                    config=config,
                )
                if is_valid:
                    final_answer = candidate_final_answer
                else:
                    final_validation_error = validation_error
            _iter_entry: Dict[str, Any] = {
                "iteration": iteration,
                "resource": resource.id,
                "model": used_model,
                "tier_preference": [t.value for t in iter_tiers],
                "selection_reason": selection_reason,
                "status": (
                    "final"
                    if final_answer
                    else ("final_rejected" if final_validation_error else "continue")
                ),
                "response_length": len(response_text),
                "validation_error": final_validation_error,
                "estimated_input_tokens": _estimate_tokens(messages),
                "elapsed_s": round(time.time() - iter_start, 1),
            }
            if _was_trimmed:
                _iter_entry["context_trimmed"] = True
            iteration_log.append(_iter_entry)

            if final_answer:
                self._log(f"Task {task.id}: got final answer at iteration {iteration}")
                self._session_storage.update_status(
                    task.id,
                    "completed",
                    final_answer=final_answer,
                )
                if get_mode_contract(InteractionMode.SCHEDULER_AGENTIC_TASK).stores_completion_artifact:
                    self._store_completion_artifact(
                        task=task,
                        role_id=config.get("role_id"),
                        goal=goal,
                        final_answer=final_answer,
                        iteration_log=iteration_log,
                        duration_seconds=round(time.time() - start_time, 1),
                        auto_extracted=False,
                        resource_id=_last_resource_id,
                        model=_last_used_model,
                    )
                break
            if final_validation_error:
                correction_prompt = (
                    "Your previous <FINAL_ANSWER> was rejected by validation: "
                    f"{final_validation_error}. "
                    "Return a corrected <FINAL_ANSWER> only."
                )
                messages.append({"role": "user", "content": correction_prompt})
                self._record(task.id, "user", correction_prompt, iteration=abs_iteration)
                continue

            # Track consecutive iterations where tools were available but unused.
            # After 2 such iterations inject a brief forcing nudge so the model
            # doesn't keep drifting in prose land when it should be acting.
            if tool_defs:
                self._consecutive_no_tool += 1
            else:
                self._consecutive_no_tool = 0

            if tool_defs and self._consecutive_no_tool >= 2:
                available_names = [t["function"]["name"] for t in tool_defs]
                next_msg = (
                    f"You have responded {self._consecutive_no_tool} times without "
                    "calling any tools. You have the following tools available: "
                    f"{available_names}. "
                    "Call a tool now to make progress, or provide your "
                    "<FINAL_ANSWER> if the task is complete."
                )
                self._consecutive_no_tool = 0  # reset after nudge
            elif iteration >= max_iterations - 1:
                remaining = max_iterations - iteration
                next_msg = NEAR_LIMIT_PROMPT.format(
                    current=iteration, max=max_iterations, remaining=remaining
                )
            else:
                next_msg = CONTINUE_PROMPT
            messages.append({"role": "user", "content": next_msg})
            self._record(task.id, "user", next_msg, iteration=abs_iteration)

        total_elapsed = round(time.time() - start_time, 1)

        # If the agent paused to ask the user a question, return early
        if self._waiting_for_input_question:
            self._session_storage.update_status(
                task.id,
                "waiting_for_input",
            )
            session_file = str(self._session_storage._path(task.id))
            return TaskResult(
                success=False,
                waiting_for_input=self._waiting_for_input_question,
                waiting_for_input_choices=self._waiting_for_input_choices,
                output_file=session_file,
                metrics={
                    "iterations": len(iteration_log),
                    "duration_seconds": total_elapsed,
                    "session_file": session_file,
                },
            )

        # ── Fallback completion recovery ──────────────────────────────────────
        # If the agent finished its work but forgot to write <FINAL_ANSWER> tags,
        # auto-extract the last response rather than sending the user a HITL question
        # for a task that's effectively done.
        #
        # Conditions (all must hold):
        #   - no final_answer found by tag parsing
        #   - no pending waiting_for_input (model didn't ask a question)
        #   - last turn had NO tool calls (model was writing, not acting)
        #   - last response is substantive (length + no in-progress patterns)
        #
        # This is a recovery mechanism, not the primary path. A proper
        # forced-finalization phase on the last iteration should be added later.
        if (
            final_answer is None
            and not self._waiting_for_input_question
            and not _last_turn_had_tool_calls
        ):
            text = _last_response_text.strip()
            _IN_PROGRESS_PATTERNS = [
                "let me continue", "i'll now", "i will now", "next i will",
                "next, i", "i need more information", "i need to", "i'll need to",
                "let me check", "let me look", "i should", "i'll start",
                "first, i", "first i'll",
            ]
            _looks_complete = (
                len(text) > 150
                and not any(p in text.lower() for p in _IN_PROGRESS_PATTERNS)
            )
            if _looks_complete:
                final_answer = text
                auto_extracted = True
                self._log(
                    f"Task {task.id}: fallback completion recovery — "
                    "auto-extracted last response (no FINAL_ANSWER tags found)"
                )

        success = final_answer is not None

        # Finalize session status if not already set
        current_session = self._session_storage.load_session(task.id)
        if current_session and current_session.status == "running":
            if success:
                self._session_storage.update_status(
                    task.id,
                    "completed",
                    final_answer=final_answer,
                )
            else:
                # Instead of hard-failing, surface a HITL question so the user
                # can grant more iterations and resume the session.
                self._waiting_for_input_question = (
                    f"Iteration budget exhausted ({max_iterations} iterations used) "
                    "without a final answer. Reply 'yes' to grant more iterations and "
                    "resume, or 'no' to mark the task as failed."
                )
                self._waiting_for_input_choices = ["yes", "no"]
                self._session_storage.update_status(task.id, "waiting_for_input")

        session_file = str(self._session_storage._path(task.id))

        if self._waiting_for_input_question:
            return TaskResult(
                success=False,
                waiting_for_input=self._waiting_for_input_question,
                waiting_for_input_choices=self._waiting_for_input_choices,
                output_file=session_file,
                metrics={
                    "iterations": len(iteration_log),
                    "iteration_log": iteration_log,
                    "duration_seconds": total_elapsed,
                    "session_file": session_file,
                },
            )

        # Write completion artifact for auto-extracted completions too.
        # The clean FINAL_ANSWER path writes inside the loop (line above the break).
        # Auto-extracted completions fall through the loop without hitting that path.
        if success and auto_extracted:
            if get_mode_contract(InteractionMode.SCHEDULER_AGENTIC_TASK).stores_completion_artifact:
                self._store_completion_artifact(
                    task=task,
                    role_id=config.get("role_id"),
                    goal=goal,
                    final_answer=final_answer,
                    iteration_log=iteration_log,
                    duration_seconds=total_elapsed,
                    auto_extracted=True,
                    resource_id=_last_resource_id,
                    model=_last_used_model,
                )

        metrics: Dict[str, Any] = {
            "iterations": len(iteration_log),
            "iteration_log": iteration_log,
            "duration_seconds": total_elapsed,
            "final_answer": final_answer,
            "session_file": session_file,
            "total_context_trims": _context_trim_count,
        }
        if auto_extracted:
            metrics["completion_mode"] = "auto_extracted"
            metrics["auto_extracted_final_answer"] = True

        # REFLECT: write task learnings back to memory (non-blocking, errors swallowed)
        if success and final_answer:
            await self._reflect_to_memory(
                goal=goal,
                role_id=config.get("role_id"),
                final_answer=final_answer,
                iteration_log=iteration_log,
            )

        return TaskResult(
            success=True,
            output_file=session_file,
            metrics=metrics,
        )

    def _store_completion_artifact(
        self,
        task: "Task",
        role_id: Optional[str],
        goal: str,
        final_answer: str,
        iteration_log: Optional[List[Dict]] = None,
        duration_seconds: float = 0.0,
        auto_extracted: bool = False,
        resource_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """
        Write a task_report_v2 artifact to ~/.memory/task_reports/{task_id}.json.

        The v2 schema carries structured sections (completed/findings/incomplete),
        execution metrics, provenance, and a promotion block, while keeping the
        legacy `content` field for backwards-compatible readers.

        In task_report_v2, `status` records execution outcome (for example
        completed or completed_fallback) and `review_status` starts as
        pending_review so the user can inspect and promote the report to the
        knowledge base. Called only when the mode contract has
        stores_completion_artifact=True (i.e. SCHEDULER_AGENTIC_TASK).
        """
        import json as _json
        from datetime import datetime as _dt
        from pathlib import Path as _Path
        from app.config.paths import get_memory_subpath

        reports_dir = _Path(get_memory_subpath("task_reports"))
        try:
            reports_dir.mkdir(parents=True, exist_ok=True)

            # Parse structured sections from the FINAL_ANSWER text
            sections = _parse_final_answer_sections(final_answer or "")

            # One-line summary: first sentence up to 150 chars
            raw = (final_answer or "").strip()
            summary = re.split(r"(?<=[.!?])\s", raw)[0][:150] if raw else ""

            # Execution metrics from iteration log
            ilog = iteration_log or []
            tool_call_count = sum(1 for e in ilog if e.get("status") == "tool_use")

            # Completion mode
            if auto_extracted:
                completion_mode = "auto_extracted_last_response"
            else:
                completion_mode = "model_final_answer"

            # Paths
            session_file = str(self._session_storage._path(task.id))
            report_path = reports_dir / f"{task.id}.json"
            now = _dt.now().isoformat()

            # Execution outcome status
            exec_status = "completed_fallback" if auto_extracted else "completed"

            report = {
                # ── Legacy fields (kept for backwards-compatible readers) ──
                "task_id": task.id,
                "role_id": role_id,
                "goal": goal,
                "status": exec_status,
                "created_at": now,
                "content": final_answer,
                # ── v2 fields ──
                "schema_version": "task_report_v2",
                "report_type": "task_completion",
                "review_status": "pending_review",
                "completed_at": now,
                "summary": summary,
                "completed": sections["completed"],
                "findings": sections["findings"],
                "incomplete": sections["incomplete"],
                "resume_hint": sections["resume_hint"],
                "final_answer": {
                    "raw_text": final_answer,
                    "completion_mode": completion_mode,
                    "auto_extracted": auto_extracted,
                    "validation_notes": [],
                },
                "artifacts": {
                    "session_file": session_file,
                    "report_file": str(report_path),
                    "output_files": [],
                    "source_files": [],
                },
                "metrics": {
                    "iterations": len(ilog),
                    "tool_calls": tool_call_count,
                    "duration_seconds": duration_seconds,
                },
                "provenance": {
                    "interaction_mode": "scheduler_agentic_task",
                    "resource_id": resource_id,
                    "model": model,
                    "task_type": "assistant",
                },
                "promotion": {
                    "eligible_for_knowledge": True,
                    "knowledge_doc_id": None,
                    "promoted_at": None,
                },
            }
            with open(report_path, "w", encoding="utf-8") as f:
                _json.dump(report, f, indent=2, ensure_ascii=False)
            self._log(f"Task {task.id}: task_report_v2 written → {report_path}")
        except Exception as e:
            self._log(
                f"Task {task.id}: failed to write completion artifact: {e}",
                level="warning",
            )

    def _load_resume_messages(
        self, task_id: str, system_prompt: str
    ) -> tuple[Optional[List[Dict]], int]:
        """
        Load messages from a previous session for resumption.
        Returns (messages, last_iteration) or (None, 0) if session not found.
        """
        session = self._session_storage.load_session(task_id)
        if session is None:
            return None, 0

        messages: List[Dict] = []
        max_iteration = 0
        for msg in session.messages:
            max_iteration = max(max_iteration, msg.iteration)
            entry: Dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            messages.append(entry)

        return messages, max_iteration

    async def _call_llm(
        self,
        resource: LLMResource,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        model_override: Optional[str] = None,
    ) -> Dict:
        """Make an LLM call via UnifiedLLMClient."""
        from app.llm.unified_client import UnifiedLLMClient
        # Resolve model (keeps OpenRouter cache logic on executor)
        headers_for_probe = {"Content-Type": "application/json"}
        if resource.api_key:
            headers_for_probe["Authorization"] = f"Bearer {resource.api_key}"
        selected_model = model_override or await self._resolve_model_for_resource(resource, headers_for_probe)

        resource_config = {
            "base_url": resource.base_url,
            "model": selected_model,
            "api_key": resource.api_key,
            "output_limit": resource.output_limit,
            "message_format": "openai",
            "provider": resource.provider,
        }
        client = UnifiedLLMClient()
        data = await client.call_async(
            messages=messages,
            resource_config=resource_config,
            model_override=selected_model,
            tools=tools,
        )
        choices = data.get("choices", [])
        if not choices:
            raise ValueError("LLM returned no choices")
        return data

    async def _resolve_model_for_resource(
        self, resource: LLMResource, headers: Dict[str, str]
    ) -> str:
        """Resolve the effective model for a resource."""
        model = resource.model or ""

        # OpenRouter auto-routing
        if self._is_openrouter_auto(resource):
            free_model = await self._get_cached_openrouter_free_model(resource, headers)
            if free_model:
                return free_model
            return model

        # Local server with no model configured — probe /v1/models
        if not model and resource.base_url:
            try:
                models_url = resource.base_url.rstrip("/").rstrip("/v1") + "/v1/models"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(models_url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json().get("data", [])
                        if data:
                            return data[0].get("id", "")
            except Exception:
                pass

        return model

    def _is_openrouter_auto(self, resource: LLMResource) -> bool:
        """Return True if this resource should auto-resolve OpenRouter free model."""
        base = (resource.base_url or "").rstrip("/")
        return base.startswith("https://openrouter.ai/api/v1") and (
            resource.model == "openrouter/auto"
        )

    async def _get_cached_openrouter_free_model(
        self, resource: LLMResource, headers: Dict[str, str]
    ) -> Optional[str]:
        """Fetch/cached OpenRouter free model id for this resource."""
        if not resource.api_key:
            return None

        now = time.time()
        cache_entry = self._openrouter_model_cache.get(resource.id)
        if cache_entry and now - cache_entry["fetched_at"] < self._openrouter_model_cache_ttl_seconds:
            return cache_entry.get("model")

        models_url = f"{resource.base_url.rstrip('/')}/models"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(models_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            self._log(f"OpenRouter model discovery failed for {resource.id}: {e}", "warning")
            return None

        model_id = self._pick_openrouter_free_model(data)
        if model_id:
            self._openrouter_model_cache[resource.id] = {
                "model": model_id,
                "fetched_at": now,
            }
            self._log(f"Resolved OpenRouter free model for {resource.id}: {model_id}")
        return model_id

    def _pick_openrouter_free_model(self, models_payload: Dict[str, Any]) -> Optional[str]:
        """Pick a free model id from OpenRouter /models payload."""
        models = models_payload.get("data")
        if not isinstance(models, list):
            return None

        free_ids: List[str] = []
        zero_price_ids: List[str] = []

        for model in models:
            if not isinstance(model, dict):
                continue
            model_id = model.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue

            if model_id.endswith(":free"):
                free_ids.append(model_id)

            pricing = model.get("pricing")
            if isinstance(pricing, dict):
                prompt = str(pricing.get("prompt", ""))
                completion = str(pricing.get("completion", ""))
                request = str(pricing.get("request", "0"))
                image = str(pricing.get("image", "0"))
                if (
                    prompt in {"0", "0.0", "0.00"}
                    and completion in {"0", "0.0", "0.00"}
                    and request in {"0", "0.0", "0.00"}
                    and image in {"0", "0.0", "0.00"}
                ):
                    zero_price_ids.append(model_id)

        if free_ids:
            return sorted(set(free_ids))[0]
        if zero_price_ids:
            return sorted(set(zero_price_ids))[0]
        return None

    # ------------------------------------------------------------------
    # ORIENT — Phase 1: search memory for relevant past context
    # ------------------------------------------------------------------

    async def _orient_from_memory(self, goal: str, role_id: Optional[str]) -> str:
        """
        Search memory for relevant past procedures and context before the loop starts.

        Two searches are run in parallel:
          - Global context search across all tiers (conversations, active, archival, knowledge)
          - Role-private knowledge search (if role_id is set and the memory service supports it)

        Returns a formatted orientation block, or "" if nothing useful is found or
        the memory service is unavailable.  Never raises.
        """
        if not self._memory_service:
            return ""
        try:
            # Search only role-scoped knowledge — never the user's personal conversations.
            # Role-private store first (Ahman's own past tasks), then shared knowledge base.
            merged: List[Dict[str, Any]] = []
            try:
                sig = inspect.signature(self._memory_service._search_knowledge_base_async)
                if "role_id" in sig.parameters:
                    # Role-scoped knowledge only — never the shared/user knowledge base.
                    if role_id:
                        merged = await self._memory_service._search_knowledge_base_async(
                            goal, max_items=6, role_id=role_id
                        )
                    # No role_id → no knowledge context (safer than leaking user personal docs)
                else:
                    # Legacy signature: no role scoping available — skip to avoid leaking user memory
                    pass
            except Exception:
                pass

            if not merged:
                return ""

            lines: List[str] = []
            for h in merged[:6]:
                content = (h.get("content") or h.get("text") or "").strip()[:400]
                source = h.get("source", "memory")
                if content:
                    lines.append(f"[{source}] {content}")

            if not lines:
                return ""

            self._log(f"ORIENT: injecting {len(lines)} memory hits for task")
            return (
                "\n\n## Orientation (from memory)\n"
                "These are COMPLETED past records — historical context only. "
                "They are not in-progress sessions. Use them to inform your plan, "
                "avoid repeating past mistakes, and build on what worked:\n"
                + "\n---\n".join(lines)
                + "\n"
            )
        except Exception as e:
            self._log(f"Memory orientation failed (continuing): {e}", "warning")
            return ""

    # ------------------------------------------------------------------
    # REFLECT — Phase 5: write learnings back to memory after completion
    # ------------------------------------------------------------------

    async def _reflect_to_memory(
        self,
        goal: str,
        role_id: Optional[str],
        final_answer: str,
        iteration_log: List[Dict[str, Any]],
    ) -> None:
        """
        Write a procedural reflection into memory after a successful task.

        Extracts:
          - Ordered list of tools used (de-duplicated, first-occurrence order)
          - A condensed outcome summary from the FINAL_ANSWER

        Writes to the role-private knowledge store when role_id is set
        (and the memory service supports it), otherwise to the shared store.
        Fire-and-forget — all errors are logged, never surfaced.
        """
        if not self._memory_service:
            return
        try:
            # Ordered unique tool sequence from the iteration log
            seen: Dict[str, int] = {}
            for entry in iteration_log:
                for t in entry.get("tool_calls", []):
                    if t not in seen:
                        seen[t] = len(seen)
            tools_used = sorted(seen, key=lambda t: seen[t])

            from datetime import datetime as _dt
            timestamp = _dt.now().strftime("%Y-%m-%d")
            lines = [
                f"[COMPLETED PAST TASK — {timestamp}]",
                f"Goal: {goal[:200]}",
            ]
            if tools_used:
                lines.append(f"Tools used (in order): {', '.join(tools_used[:15])}")
            answer_excerpt = (final_answer or "").strip()[:500]
            if answer_excerpt:
                lines.append(f"Outcome:\n{answer_excerpt}")

            document = "\n".join(lines)
            metadata: Dict[str, Any] = {
                "type": "task_reflection",
                "role": role_id,
                "goal_prefix": goal[:100],
                "tools_used": tools_used[:15],
            }

            # Route to role-private store when supported
            try:
                sig = inspect.signature(self._memory_service.add_to_knowledge_base)
                if "role_id" in sig.parameters:
                    self._memory_service.add_to_knowledge_base(document, metadata, role_id=role_id)
                else:
                    self._memory_service.add_to_knowledge_base(document, metadata)
            except TypeError:
                self._memory_service.add_to_knowledge_base(document, metadata)

            self._log(
                f"REFLECT: wrote task learnings to memory "
                f"(role={role_id}, tools={tools_used[:5]})"
            )
        except Exception as e:
            self._log(f"Memory reflection failed (non-fatal): {e}", "warning")

    async def _execute_tool_calls(self, tool_calls: List[Dict]) -> List[str]:
        """Execute tool calls and return results as strings."""
        # Defensive dedup: some local models (e.g. Gemma 4) ignore
        # parallel_tool_calls=false and batch dozens of identical calls.
        # Keep only the first occurrence of each (name, args) pair so the
        # model gets one result per unique call instead of 87 errors.
        _MAX_CALLS_PER_TURN = 10
        seen_signatures: set = set()
        deduped: List[Dict] = []
        for tc in tool_calls:
            sig = (
                tc.get("function", {}).get("name", ""),
                json.dumps(tc.get("function", {}).get("arguments", ""), sort_keys=True),
            )
            if sig not in seen_signatures:
                seen_signatures.add(sig)
                deduped.append(tc)
        if len(tool_calls) != len(deduped):
            self._log(
                f"Deduped {len(tool_calls)} tool calls → {len(deduped)} unique "
                "(model ignored parallel_tool_calls=false)",
                "warning",
            )
        if len(deduped) > _MAX_CALLS_PER_TURN:
            self._log(
                f"Capping tool calls from {len(deduped)} → {_MAX_CALLS_PER_TURN} per turn",
                "warning",
            )
            deduped = deduped[:_MAX_CALLS_PER_TURN]
        tool_calls = deduped

        results = []
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            raw_args = tc.get("function", {}).get("arguments", "")
            # Some OpenAI-compatible backends already parse arguments into a dict;
            # others return a JSON string.  Handle both shapes.
            if isinstance(raw_args, dict):
                fn_args = raw_args
            elif not raw_args:
                fn_args = {}
            else:
                try:
                    fn_args = json.loads(raw_args)
                except (json.JSONDecodeError, ValueError, TypeError) as parse_err:
                    # Return a clear error so the model can self-correct its JSON
                    self._log(
                        f"Tool {fn_name}: argument JSON parse failed — {parse_err}", "warning"
                    )
                    results.append(
                        json.dumps({
                            "error": (
                                f"Your tool call arguments for '{fn_name}' were not valid JSON "
                                f"({parse_err}). Please call the tool again with properly "
                                "formatted JSON arguments."
                            )
                        })
                    )
                    continue

            try:
                result = await self._execute_single_tool(fn_name, fn_args)
                result_str = json.dumps(result, default=str)
                # Cap large outputs from file/shell tools to prevent context bloat
                if fn_name in _TOOL_OUTPUT_LARGE_TOOLS and len(result_str) > _TOOL_OUTPUT_CAP_CHARS:
                    result_str = (
                        result_str[:_TOOL_OUTPUT_CAP_CHARS]
                        + f'... [truncated {len(result_str) - _TOOL_OUTPUT_CAP_CHARS} chars by context guard]'
                    )
                results.append(result_str)
            except Exception as e:
                self._log(f"Tool {fn_name} failed: {e}", "error")
                results.append(json.dumps({"error": str(e)}))
        return results

    async def _execute_single_tool(self, name: str, args: Dict) -> Any:
        """Execute a single tool from dynamic registry or built-in tools."""
        # Enforce capabilities: reject calls to tools not in the enabled list.
        # ask_user is always permitted (HITL escape hatch injected unconditionally).
        enabled = getattr(self, "_enabled_tool_names", None)
        if enabled is not None and name != "ask_user" and name not in enabled:
            self._log(
                f"Tool '{name}' blocked: not in role/task capabilities list "
                f"({len(enabled)} tools enabled)",
                "warning",
            )
            return {
                "error": (
                    f"Tool '{name}' is not available for this role/task. "
                    f"Available tools: {sorted(enabled)}"
                )
            }

        # Get tool from registry for policy/gate check
        tool = self._tool_registry.get_tool(name)

        # SecurityGate: composes SafetyPolicy + danger budget + plan scope.
        gate_result = self._gate.check(
            task_id=self._current_task_id or "",
            tool_name=name,
            tool_def=tool.to_dict() if tool else None,
            args=args,
        )
        if gate_result.decision == SecurityDecision.HARD_STOP:
            self._log(f"Tool '{name}' hard-blocked by gate: {gate_result.reason}", "warning")
            await self._emit_policy_violation(
                task_id=self._current_task_id,
                tool_name=name,
                layer="security_gate",
                checker=gate_result.rule_source or "safety",
                decision="block",
                reason=gate_result.reason,
                severity="error",
            )
            return {"error": f"Security gate blocked: {gate_result.reason}"}
        if gate_result.decision == SecurityDecision.STOP_ASK_USER:
            self._log(f"Gate escalating '{name}' to ask_user: {gate_result.reason}", "warning")
            self._waiting_for_input_question = gate_result.ask_question or gate_result.reason
            self._waiting_for_input_choices = ["continue", "cancel"]
            self._gate_escalation_pending = True
            return {"success": True, "message": f"Security gate paused: {gate_result.reason}"}
        if gate_result.decision == SecurityDecision.WARN_ALLOW:
            self._log(gate_result.warn_message or gate_result.reason, "warning")

        # Check role policy (allowed_tools ceiling, denied_tools, per-task limits)
        role_decision = self._policy_monitor.check(name, args)
        if not role_decision.allowed:
            self._log(f"Tool '{name}' blocked by role policy: {role_decision.reason}", "warning")
            # Severity: content/data_boundary matches are "warning"; static/context blocks are "error"
            violation_severity = (
                "warning"
                if role_decision.metadata.get("pattern_severity") == "warn"
                else "error"
            )
            await self._emit_policy_violation(
                task_id=self._current_task_id,
                tool_name=name,
                layer="role",
                checker=role_decision.checker,
                decision="block",
                reason=role_decision.reason,
                severity=violation_severity,
                metadata=role_decision.metadata,
            )
            return {"error": f"Role policy blocked: {role_decision.reason}"}
        if role_decision.warn:
            self._log(f"Role policy warning for '{name}': {role_decision.reason}", "warning")
        self._policy_monitor.record_call(name)

        # Handle ask_user: pause execution and wait for user reply
        if name == "ask_user":
            # Enforce behavior_rules.exhausts_tools_before_asking — agent must
            # attempt at least one other tool before escalating to the user.
            if self._exhausts_tools_before_asking and self._tool_calls_made == 0:
                available = [
                    t for t in getattr(self, "_enabled_tool_names", [])
                    if t != "ask_user"
                ]
                hint = f" Try one of: {available}." if available else ""
                return {
                    "error": (
                        "behavior_rules.exhausts_tools_before_asking is active. "
                        "You must attempt at least one other tool before asking the user."
                        + hint
                    )
                }
            question = args.get("question", "")
            choices = args.get("choices")

            # Budget extension request: agent signals it needs more cycles rather
            # than a genuine HITL blocker. Grant automatically up to the cap.
            if question.strip().startswith(_BUDGET_EXTENSION_PREFIX):
                import re as _re
                match = _re.search(r"Need\s+(\d+)\s+more", question, _re.IGNORECASE)
                grant = min(int(match.group(1)) if match else 10, _BUDGET_EXTENSION_MAX_GRANT)
                self._budget_extension_granted += grant
                self._log(
                    f"Task {self._current_task_id}: budget extension granted (+{grant} iterations). "
                    f"Message: {question[:120]}"
                )
                return {
                    "success": True,
                    "message": f"Budget extended by {grant} iterations. Continue your work.",
                }

            self._waiting_for_input_question = question
            self._waiting_for_input_choices = choices if isinstance(choices, list) else None
            result_msg = f"Question submitted to user: {question}"
            if choices:
                result_msg += f" (choices: {choices})"
            return {"success": True, "message": result_msg}

        # Count non-ask_user tool calls for behavior_rules enforcement
        self._tool_calls_made += 1

        # tmux tools may accept a per-call "socket" override, but do not force
        # one here. The tmux MCP backend may already be configured with a fixed
        # socket/server in ~/.memory/config/mcp_servers.json, and overriding it
        # blindly hides real sessions from the agent.

        # Try dynamic registry first
        try:
            result = await self._tool_registry.execute_tool(name, args)
            # Registry signals "ask the user" on behalf of the tool (e.g. non-existent role dispatch)
            if result.get("__ask_user__"):
                return await self._execute_tool(
                    "ask_user",
                    {"question": result["question"], "choices": result.get("choices")},
                )
            if result.get("success"):
                self._policy.track_operation(
                    operation="execute", tool_name=name, success=True
                )
                return result
            # "Tool not found" means it's a builtin — fall through to builtin handlers.
            # Any other failure is a real error — return it to the LLM.
            err = result.get("error", "")
            if not (err.endswith("not found") or "not found" in err):
                return {"error": err or f"Tool '{name}' failed"}
        except Exception as e:
            self._log(f"Dynamic tool {name} failed: {e}", "error")

        # Fallback to built-in tools
        if name == "memory_search" and self._memory_service:
            query = args.get("query", "")
            results = await self._memory_service._search_knowledge_base_async(
                query, max_items=5, role_id=self._role_id
            )
            return {"query": query, "results": results, "count": len(results)}

        if name.startswith("browser_") or name == "browser":
            return await self._execute_browser_facade(name, args)

        if name in ("google_calendar_list", "google_calendar_create"):
            return await self._execute_google_calendar(name, args)

        return {"error": f"Unknown or unavailable tool: {name}"}

    # --- Google Calendar bridge -------------------------------------------------

    async def _execute_google_calendar(self, name: str, args: Dict) -> Dict:
        """Dispatch google_calendar_list / google_calendar_create to the gws bridge."""
        from app.scheduler.google_calendar_bridge import (
            calendar_list_events,
            calendar_create_event,
        )
        if name == "google_calendar_list":
            return await calendar_list_events(
                start_date=args.get("start_date", ""),
                end_date=args.get("end_date", ""),
                calendar_id=args.get("calendar_id", "primary"),
                max_results=int(args.get("max_results", 20)),
            )
        if name == "google_calendar_create":
            return await calendar_create_event(
                title=args.get("title", ""),
                start_at=args.get("start_at", ""),
                end_at=args.get("end_at"),
                details=args.get("details", ""),
                calendar_id=args.get("calendar_id", "primary"),
                timezone=args.get("timezone", "Asia/Taipei"),
                duration_minutes=int(args.get("duration_minutes", 30)),
            )
        return {"error": f"Unknown google calendar tool: {name}"}

    # --- browser facade ---------------------------------------------------------

    _BROWSER_ROUTES: Dict[str, tuple] = {
        "navigate":   ("browser_navigate",        lambda a: {"url": a.get("url", "")}),
        "back":       ("browser_navigate_back",   lambda a: {}),
        "click":      ("browser_click",  lambda a: {
            "ref": a.get("ref") or a.get("selector", ""),
            "element": a.get("element", a.get("ref") or a.get("selector", "")),
        }),
        "hover":      ("browser_hover",  lambda a: {
            "ref": a.get("ref") or a.get("selector", ""),
            "element": a.get("element", a.get("ref") or a.get("selector", "")),
        }),
        "type":       ("browser_type",   lambda a: {
            "ref": a.get("ref") or a.get("selector", ""),
            "element": a.get("element", a.get("ref") or a.get("selector", "")),
            "text": a.get("text", ""),
        }),
        "fill_form":  ("browser_fill_form",       lambda a: {"fields": a.get("fields", {})}),
        "select":     ("browser_select_option",   lambda a: {"selector": a.get("selector", ""), "value": a.get("value", "")}),
        "press_key":  ("browser_press_key",       lambda a: {"key": a.get("key", "")}),
        "snapshot":   ("browser_snapshot",        lambda a: {}),
        "screenshot": ("browser_take_screenshot", lambda a: {}),
        "wait_for":   ("browser_wait_for",        lambda a: {k: v for k, v in {
            "text": a.get("text_to_wait"), "timeout": a.get("timeout_ms")}.items() if v is not None}),
        "tabs":       ("browser_tabs",            lambda a: {k: v for k, v in {
            "action": a.get("tab_action"), "tab_id": a.get("tab_id")}.items() if v is not None}),
        "evaluate":   ("browser_evaluate",        lambda a: {"expression": a.get("expression", "")}),
        "console":    ("browser_console_messages",lambda a: {}),
        "network":    ("browser_network_requests",lambda a: {}),
        "close":      ("browser_close",           lambda a: {}),
    }

    async def _execute_browser_facade(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route browser_* tools (and legacy browser(action=...) facade) to the playwright MCP server.

        Individual tools: browser_navigate, browser_snapshot, browser_screenshot,
                          browser_click, browser_type, browser_press_key
        Legacy facade:    browser(action='navigate', ...)
        """
        # Map tool name → (playwright tool name suffix, arg_builder)
        # Playwright MCP uses 'ref' (from snapshot) + 'element' (human label), not 'selector'.
        # Individual tools use the tool name directly; legacy facade uses action param.
        _INDIVIDUAL_MAP: Dict[str, tuple] = {
            "browser_navigate":   ("browser_navigate",        lambda a: {"url": a.get("url", "")}),
            "browser_snapshot":   ("browser_snapshot",        lambda a: {}),
            "browser_screenshot": ("browser_take_screenshot", lambda a: {}),
            "browser_click":      ("browser_click",           lambda a: {
                "ref": a.get("ref") or a.get("selector", ""),
                "element": a.get("element", a.get("ref") or a.get("selector", "")),
            }),
            "browser_type":       ("browser_type",            lambda a: {
                "ref": a.get("ref") or a.get("selector", ""),
                "element": a.get("element", a.get("ref") or a.get("selector", "")),
                "text": a.get("text", ""),
            }),
            "browser_press_key":  ("browser_press_key",       lambda a: {"key": a.get("key", "")}),
        }

        if name in _INDIVIDUAL_MAP:
            pw_tool, arg_builder = _INDIVIDUAL_MAP[name]
        elif name == "browser":
            # Legacy enum facade
            action = args.get("action", "")
            if action not in self._BROWSER_ROUTES:
                return {"error": f"Unknown browser action '{action}'. Valid: {sorted(self._BROWSER_ROUTES)}"}
            pw_tool, arg_builder = self._BROWSER_ROUTES[action]
        else:
            return {"error": f"Unknown browser tool: {name}"}

        built_args = arg_builder(args)

        # Try via mcp_client_manager (playwright server)
        if self._mcp_client_manager:
            try:
                result = await self._mcp_client_manager.call_tool("playwright", pw_tool, built_args)
                return result
            except Exception as e:
                return {"error": f"{name} via playwright MCP failed: {e}"}

        # Fallback: try the registry directly (playwright__ prefix)
        reg_name = f"playwright__{pw_tool}"
        try:
            result = await self._tool_registry.execute_tool(reg_name, built_args)
            return result
        except Exception as e:
            return {"error": f"{name} failed: playwright MCP not available. {e}"}

    async def _emit_policy_violation(
        self,
        task_id: Optional[str],
        tool_name: str,
        layer: str,
        checker: str,
        decision: str,
        reason: str,
        severity: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Emit a policy_violation event to the EventLog.

        This makes every block/warn visible via ntfy, dashboard, and
        get_content — no violations are silent. Never raises.
        """
        try:
            from app.mcp.adapters.event_log import EventLog
            event_log = EventLog()
            await event_log.append({
                "event_type": "policy_violation",
                "severity": severity,
                "task_type": "policy",
                "notify_user": True,
                "title": f"Policy blocked: {tool_name}",
                "task_id": task_id,
                "role_id": self._role_id,
                "layer": layer,
                "checker": checker,
                "tool_name": tool_name,
                "decision": decision,
                "reason": reason,
                "metadata": metadata or {},
            })
        except Exception:
            pass  # violation logging must never break task execution

    def _parse_final_answer(self, text: str) -> Optional[str]:
        """Extract content between <FINAL_ANSWER> tags, if present."""
        tag_open = "<FINAL_ANSWER>"
        tag_close = "</FINAL_ANSWER>"
        start = text.find(tag_open)
        if start == -1:
            return None
        start += len(tag_open)
        end = text.find(tag_close, start)
        if end == -1:
            # Tag opened but not closed — treat the rest as the answer
            return text[start:].strip()
        return text[start:end].strip()

    def _resolve_capabilities(self, role: dict) -> List[str]:
        """
        Expand role.capabilities into executable tool names via capability_catalog.json.

        capabilities entries may be:
          - a category name  (e.g. "web", "memory") — all tools in that category are included
          - an explicit tool name (e.g. "curl_request", "get_verge_tech_news") — included directly

        Precedence:
          1. role.capabilities (categories or explicit tool names) — catalog-based path
          2. ["memory_search"] — default fallback
        """
        from app.config.config_loader import load_layered_json_config

        capabilities = role.get("capabilities")

        if capabilities is not None:
            try:
                catalog = load_layered_json_config("config/capability_catalog.json")
            except Exception:
                catalog = {}
            tool_entries = catalog.get("tools", {})

            # Partition capabilities into known categories vs explicit tool names
            known_categories = {
                meta.get("category")
                for meta in tool_entries.values()
                if isinstance(meta, dict) and meta.get("category")
            }
            # Also include categories from the dynamic registry
            for t_def in self._tool_registry._tools.values():
                if t_def.category:
                    known_categories.add(t_def.category)

            access_categories = {e for e in capabilities if e in known_categories}
            access_explicit = {e for e in capabilities if e not in known_categories}

            names = []
            seen = set()
            # Catalog-defined tools — include by category match
            for tool_name, tool_meta in tool_entries.items():
                if not isinstance(tool_meta, dict):
                    continue
                if tool_meta.get("always_injected"):
                    continue
                if tool_meta.get("internal"):  # facade-only; never expose raw to LLM
                    continue
                if tool_meta.get("category") in access_categories:
                    names.append(tool_name)
                    seen.add(tool_name)
            # Registry-defined tools — include by category match or explicit name
            for t_name, t_def in self._tool_registry._tools.items():
                if t_name in seen:
                    continue
                # Skip internal/raw tools registered by MCP servers that have
                # a catalog entry marked internal (e.g. playwright__ tools)
                cat_meta = tool_entries.get(t_name, {})
                if isinstance(cat_meta, dict) and cat_meta.get("internal"):
                    continue
                if (t_def.category and t_def.category in access_categories) or t_name in access_explicit:
                    names.append(t_name)
                    seen.add(t_name)
            # Explicit names not yet resolved — include directly if they exist in either catalog or registry
            for t_name in access_explicit:
                if t_name in seen:
                    continue
                if t_name in tool_entries or self._tool_registry.get_tool(t_name):
                    names.append(t_name)
            return names
        else:
            return ["memory_search"]

    def _determine_tier_preference_for_iteration(
        self,
        base_tiers: List[ResourceTier],
        goal: str,
        config: Dict[str, Any],
        iteration_log: List[Dict[str, Any]],
    ) -> tuple[List[ResourceTier], str]:
        """Dynamically choose tier order per iteration based on task complexity and recent failures."""
        policy = config.get("resource_policy", {})
        if not policy.get("enabled", True):
            return base_tiers, "static_policy_disabled"

        complexity = self._estimate_task_complexity(goal, config)
        prefer_api_for_complex = bool(
            policy.get("prefer_api_for_complex_tasks", True)
        )
        allow_paid_for_complex = bool(
            policy.get("allow_paid_for_complex_tasks", False)
        )

        if complexity >= 3 and prefer_api_for_complex:
            dynamic_tiers: List[ResourceTier] = [ResourceTier.FREE_API, ResourceTier.FREE]
        else:
            dynamic_tiers = [ResourceTier.FREE, ResourceTier.FREE_API]

        if allow_paid_for_complex and complexity >= 4:
            dynamic_tiers.append(ResourceTier.PAID)

        # Respect user-provided tier list as an allowlist.
        allow = set(base_tiers)
        dynamic_tiers = [t for t in dynamic_tiers if t in allow]
        if not dynamic_tiers:
            dynamic_tiers = base_tiers

        # If recent iterations show repeated failure on first tier, flip order.
        recent = iteration_log[-3:]
        if len(recent) >= 2:
            first_tier = dynamic_tiers[0]
            failed = 0
            for item in recent:
                rid = item.get("resource")
                if item.get("status") == "error" and rid:
                    r = self._rm._resources.get(rid)
                    if r and r.tier == first_tier:
                        failed += 1
            if failed >= 2 and len(dynamic_tiers) > 1:
                dynamic_tiers = dynamic_tiers[1:] + dynamic_tiers[:1]
                return (
                    dynamic_tiers,
                    f"dynamic_flip_after_{failed}_recent_{first_tier.value}_errors",
                )

        return dynamic_tiers, f"dynamic_complexity_{complexity}"

    def _estimate_task_complexity(self, goal: str, config: Dict[str, Any]) -> int:
        """Estimate task complexity on a small 1-5 scale."""
        text = (goal or "").lower()
        score = 1
        if len(text) > 300:
            score += 1
        hard_keywords = [
            "architecture",
            "refactor",
            "debug",
            "investigate",
            "analyze",
            "design",
            "multi-step",
            "integration",
            "policy",
        ]
        if any(k in text for k in hard_keywords):
            score += 2
        if config.get("available_tools"):
            score += 1
        max_iter = int(config.get("max_iterations", 1) or 1)
        if max_iter >= 6:
            score += 1
        return max(1, min(score, 5))

    def _validate_final_answer(
        self, final_answer: str, goal: str, config: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """Validate final answer quality gates before marking task completed."""
        if not final_answer or not final_answer.strip():
            return False, "empty final answer"

        answer = final_answer.strip()
        if "<FINAL_ANSWER>" in answer or "</FINAL_ANSWER>" in answer:
            return False, "nested FINAL_ANSWER tags are not allowed"

        req = config.get("final_answer_requirements", {})
        if isinstance(req, str):
            req = {}  # plain-string hint — no structured constraints
        min_length = int(req.get("min_length", 1))
        max_length = req.get("max_length")
        if len(answer) < min_length:
            return False, f"answer shorter than min_length={min_length}"
        if isinstance(max_length, int) and len(answer) > max_length:
            return False, f"answer longer than max_length={max_length}"

        must_include = req.get("must_include", [])
        if isinstance(must_include, list):
            for token in must_include:
                if token and token not in answer:
                    return False, f"missing required token '{token}'"

        exact_text = req.get("exact_text") or self._infer_exact_text_from_goal(goal)
        if exact_text:
            normalized = answer.strip().strip('"').strip("'")
            if normalized != exact_text:
                return False, f"must equal exact_text '{exact_text}'"

        # Guard against leaking planning boilerplate into final answer for "exact" asks.
        if exact_text and ("## Phase" in answer or "Phase 1:" in answer):
            return False, "final answer contains planning boilerplate"

        semantic_ok, semantic_error = self._validate_semantic_completion(
            final_answer=answer,
            goal=goal,
            config=config,
        )
        if not semantic_ok:
            return False, semantic_error

        return True, None

    def _validate_semantic_completion(
        self, final_answer: str, goal: str, config: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        Catch semantically bogus "completed" answers that claim blocker/tool
        limitations despite available tools never being attempted.

        This is intentionally narrow and conservative: it only triggers when
        the answer itself claims an availability/blocker problem while the
        current task had relevant tools enabled and the model made zero tool
        calls during this execution.
        """
        lower = final_answer.lower()
        enabled = set(getattr(self, "_enabled_tool_names", []) or [])

        blocker_markers = [
            "tool constraints",
            "tool limitation",
            "tool limitations",
            "filesystem access",
            "file system access",
            "unavailable tool",
            "unknown or unavailable tool",
            "cannot read actual task session",
            "need filesystem access",
            "mcp tool integration",
        ]
        mentions_blocker = any(marker in lower for marker in blocker_markers)

        has_relevant_tools = bool(
            {"read_file", "list_files", "search_in_files", "task_session_read", "task_report_read"} & enabled
        )

        if mentions_blocker and has_relevant_tools and self._tool_calls_made == 0:
            return (
                False,
                "final answer claims missing/unavailable file or task-session access "
                "without attempting the available tools",
            )

        # Optional task-level contract for callers that need stricter semantics.
        contract = config.get("result_contract") or {}
        if contract.get("requires_tool_use") and self._tool_calls_made == 0:
            return False, "result_contract requires at least one successful tool attempt"

        if contract.get("requires_output_file"):
            output_files = contract.get("expected_output_files") or []
            if output_files:
                missing = [p for p in output_files if not os.path.exists(os.path.expanduser(p))]
                if missing:
                    return False, f"required output files not written: {missing}"

        return True, None

    def _infer_exact_text_from_goal(self, goal: str) -> Optional[str]:
        """Infer exact output requirement from goal text when user asks for exact output."""
        text = goal or ""
        lower = text.lower()
        markers = [
            "containing exactly:",
            "exactly:",
            "exact text:",
            "exact output:",
        ]
        for marker in markers:
            idx = lower.find(marker)
            if idx == -1:
                continue
            raw = text[idx + len(marker) :].strip()
            if not raw:
                return None
            # Stop at first line break to avoid capturing extra instructions.
            raw = raw.splitlines()[0].strip()
            return raw.strip().strip('"').strip("'")
        return None
