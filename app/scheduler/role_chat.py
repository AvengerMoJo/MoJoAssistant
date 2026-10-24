"""
Role Chat Interface — conversational mode for assistant roles.

Provides direct, personality-aware conversation with a role using its
accumulated knowledge units as context. Runs a mini agentic loop (up to
MAX_CHAT_ITERATIONS) so the role can call tools (memory_search, task_search)
based on its capabilities configuration.

Chat mode is a **private recall/debrief** surface — read-only memory tools
only. Web search, browser, and orchestration tools are not available here.
A chat-mode addendum is injected into every system prompt to make this
contract explicit to the model and prevent it from planning for tools it
does not have.

Session history persists at ~/.memory/roles/{role_id}/chat_history/{session_id}.json
"""
# [mojo-integration]

from __future__ import annotations

import asyncio
import time
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from app.config.paths import get_memory_subpath
from app.roles.role_manager import RoleManager
from app.scheduler.interaction_mode import InteractionMode, get_mode_contract
from app.scheduler.ninechapter import build_behavioral_overlay
from app.scheduler.resource_pool import ResourceBusyError
from app.roles.owner_context import load_owner_profile, build_owner_context_slice

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 10    # conversation turns carried into context
MAX_KU_ITEMS = 8          # knowledge units injected as context
MAX_KU_QUOTE_CHARS = 200  # truncate long KU quotes
MAX_CHAT_ITERATIONS = 5   # max tool-call iterations per exchange
CHAT_QUEUE_WAIT_MAX_SECONDS = 180   # longest a chat call waits for the model's free request slot
ROUTED_TASK_MAX_SECONDS = 900   # wall-clock budget of a task created by route_to_role
STREAM_FALLBACK_KEEPALIVE_INTERVAL = 15  # seconds between SSE keepalives during blocking fallback

# Maps tool catalog categories → concrete tool names available in chat mode.
# Filtered at runtime by the active mode contract's allowed_tool_categories.
_CHAT_TOOL_ACCESS: Dict[str, List[str]] = {
    "memory": ["memory_search", "task_search"],
    "knowledge": ["knowledge_search"],
    # Roster and routing. Only modes whose contract allows "orchestration" (the owner hub) expose them;
    # the general dispatch tools stay out of chat.
    "orchestration": ["list_roles", "route_to_role", "routed_tasks"],
}

# OpenAI-format tool definitions for each supported chat tool
_TOOL_DEFS: Dict[str, Dict] = {
    "routed_tasks": {
        "type": "function",
        "function": {
            "name": "routed_tasks",
            "description": (
                "Status and result of the requests you handed to other assistants with route_to_role "
                "(newest first): assistant, status, and the answer or the question it is waiting on. "
                "Read-only, and covers only tasks you routed -- nothing else those assistants hold."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "One routed task. Omit to list recent ones."},
                    "limit": {"type": "integer", "description": "How many to list (default 5)"},
                },
                "required": [],
            },
        },
    },
    "route_to_role": {
        "type": "function",
        "function": {
            "name": "route_to_role",
            "description": (
                "Hand the owner's request to another assistant as a scheduled task. Use it only when the "
                "owner asks for it or agrees to it. The assistant works under the normal scheduler gates and "
                "replies to the owner itself. Returns the task id. Does not return the assistant's result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "role_id": {"type": "string", "description": "Assistant to hand the request to (see list_roles)"},
                    "message": {"type": "string", "description": "The owner's request, in their own words, with the context the assistant needs"},
                },
                "required": ["role_id", "message"],
            },
        },
    },
    "list_roles": {
        "type": "function",
        "function": {
            "name": "list_roles",
            "description": (
                "List the other assistants (roles): id, name, what each is for, and its capabilities. "
                "Read-only. Use it to answer who can do what, or who to hand a request to."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "capability": {
                        "type": "string",
                        "description": "Only roles with this capability (e.g. 'web', 'file'). Omit to list all.",
                    },
                },
                "required": [],
            },
        },
    },
    "memory_search": {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": (
                "Search your own memory — knowledge units and past task reports scoped to "
                "your role. Does NOT access the user's personal conversation history."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "max_items": {
                        "type": "integer",
                        "description": "Max results to return (default 5)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    "task_search": {
        "type": "function",
        "function": {
            "name": "task_search",
            "description": (
                "Search your own task history — completed, failed, or running tasks. "
                "Use this to answer questions about what you have done, when, and what "
                "the outcomes were. Supports filtering by keyword, date range, and status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Keyword(s) to match against task goal and result summary. "
                            "Leave empty to list tasks without keyword filtering."
                        ),
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Start date filter, ISO format or YYYY-MM-DD (inclusive).",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "End date filter, ISO format or YYYY-MM-DD (inclusive).",
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by status: completed, failed, running. Leave empty for all.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max tasks to return (default 10, max 50).",
                    },
                },
                "required": [],
            },
        },
    },
    "knowledge_search": {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": (
                "Search your own personal knowledge base — your distilled knowledge units "
                "and your own completed research reports. This is your private knowledge, "
                "scoped only to you. Other assistants cannot see it and you cannot see theirs. "
                "Use this to retrieve your own findings, analysis, and prior research in full. "
                "More complete than task_search: returns full content, not just a summary snippet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to match against task goals and report content.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max reports to return (default 5).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    "refer_to_role": {
        "type": "function",
        "function": {
            "name": "refer_to_role",
            "description": (
                "Refer the user to another assistant who may be better suited for this question. "
                "Use this when the question falls outside your expertise or when another role has "
                "specific knowledge that would provide a better answer. The referral includes a "
                "brief explanation of why the other role is better suited."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "role_id": {
                        "type": "string",
                        "description": "The role_id of the assistant to refer to (e.g., 'researcher', 'analyst', 'coder').",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation of why this role is better suited for the question.",
                    },
                    "context_summary": {
                        "type": "string",
                        "description": "Summary of the current conversation context to pass to the referred role.",
                    },
                },
                "required": ["role_id", "reason"],
            },
        },
    },
}

_FINAL_TOOL_LOOP_PROMPT = (
    "You have reached the tool-call limit for this chat turn. "
    "Do not call any more tools. "
    "Using only the conversation and tool results already available, "
    "answer the user directly now."
)

# Hollow phrases that indicate the model failed to produce a real answer.
_HOLLOW_PATTERNS = (
    "let me search",
    "i'll search",
    "let me look",
    "searching for",
    "i'll look into",
    "let me find",
    "i need to search",
)


def _ensure_response_quality(response: str, role_name: str) -> str:
    """
    Safety net for blocked/hollow chat responses.

    If the model returns empty output or a hollow placeholder phrase instead
    of a real answer, substitute a structured fallback that tells the user
    what happened and how to proceed.  The prompt overlay handles most cases;
    this catches the remainder.
    """
    text = response.strip()
    if not text:
        return (
            f"**What I found:** nothing in my current memory on this topic.\n"
            f"**What I could not confirm:** the full answer — I do not have "
            f"enough context in this session.\n"
            f"**To investigate further:** Route this as a scheduled research "
            f"task through MoJo's task flow and I can give you a complete answer."
        )
    lower = text.lower()
    if any(lower.startswith(p) for p in _HOLLOW_PATTERNS) and len(text) < 120:
        return (
            f"**What I found:** nothing conclusive in my current memory.\n"
            f"**What I could not confirm:** the full answer requires a fresh "
            f"investigation beyond what's available in this debrief session.\n"
            f"**To investigate further:** Route this as a scheduled research "
            f"task through MoJo's task flow."
        )
    return response

# The default chat-mode overlay is sourced from the DASHBOARD_CHAT mode contract.
# Roles may override it via mode_overlays.dashboard_chat in their config.
# Kept as a module-level alias for backwards compatibility with any callers that
# reference it directly.
_CHAT_MODE_ADDENDUM = get_mode_contract(InteractionMode.DASHBOARD_CHAT).prompt_overlay

# Sections in a role's full agentic system_prompt that describe tools unavailable
# in chat mode.  Stripping them prevents the model from planning for tools it
# doesn't have (e.g. trying to call `knowledge` after reading the how-to section).
_CHAT_MODE_STRIP_SECTIONS = [
    "## How you use tools",
    "## Accessing MoJoAssistant's own codebase and docs",
    "## When a tool is unavailable",
]


def _strip_tool_sections(prompt: str) -> str:
    """Remove agentic tool-instruction sections from a system prompt for chat mode."""
    import re
    for heading in _CHAT_MODE_STRIP_SECTIONS:
        # Match from the heading line up to (but not including) the next ## heading
        # or end of string.  re.DOTALL so . matches newlines.
        pattern = re.escape(heading) + r".*?(?=\n## |\Z)"
        prompt = re.sub(pattern, "", prompt, flags=re.DOTALL)
    # Collapse runs of 3+ blank lines left behind by the removal
    prompt = re.sub(r"\n{3,}", "\n\n", prompt)
    return prompt.strip()


class RoleChatSession:
    """
    One conversational session with a role.

    Each `exchange()` call adds one user→assistant turn to the session
    history and returns the assistant's response. The role's personality
    (system prompt) and recent knowledge units are prepended as context.

    If the role has capabilities (memory, web), exchange() runs a mini
    agentic loop so the role can look things up before answering.
    """

    _max_data_scope: Optional[str] = None  # per-instance value comes from the role file (see __init__)

    def __init__(
        self,
        role_id: str,
        session_id: Optional[str] = None,
        mode: InteractionMode = InteractionMode.DASHBOARD_CHAT,
        scheduler: Optional[Any] = None,
        routable_roles: Optional[List[str]] = None,
    ):
        self.role_id = role_id
        self.mode = mode
        # Widest place this role's chat data may go (DATA_SCOPES); None = unrestricted. Set in the role file.
        self._max_data_scope: Optional[str] = (RoleManager().get(role_id) or {}).get("data_scope")
        self._scheduler = scheduler            # needed only by route_to_role
        self._routable_roles = routable_roles  # None = any existing role except this one
        self.session_id = (
            session_id
            or f"chat_{role_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        self._session_dir = (
            Path(get_memory_subpath("roles")) / role_id / "chat_history"
        )
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._session_file = self._session_dir / f"{self.session_id}.json"

    # ------------------------------------------------------------------ #
    # Session persistence                                                  #
    # ------------------------------------------------------------------ #

    def _load_session(self) -> Dict[str, Any]:
        if self._session_file.exists():
            try:
                with open(self._session_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"RoleChatSession: failed to load {self.session_id}: {e}")
        session_type = {
            InteractionMode.OWNER_ONE_ON_ONE: "owner_one_on_one",
            InteractionMode.OWNER_HUB: "owner_hub",
        }.get(self.mode, "chat")
        return {
            "session_id": self.session_id,
            "role_id": self.role_id,
            "started_at": datetime.now().isoformat(),
            "session_type": session_type,
            "exchanges": [],
        }

    def _save_session(
        self, session: Dict[str, Any], user_msg: str, assistant_msg: str
    ) -> None:
        session["last_active"] = datetime.now().isoformat()
        session["exchanges"].append({
            "user": user_msg,
            "assistant": assistant_msg,
            "timestamp": datetime.now().isoformat(),
        })
        try:
            with open(self._session_file, "w", encoding="utf-8") as f:
                json.dump(session, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"RoleChatSession: failed to save session: {e}")

    # ------------------------------------------------------------------ #
    # Knowledge unit context                                               #
    # ------------------------------------------------------------------ #

    def _load_ku_context(self) -> str:
        ku_dir = (
            Path(get_memory_subpath("roles")) / self.role_id / "knowledge_units"
        )
        if not ku_dir.exists():
            return ""

        # Collect archive files at any nesting depth (handles both flat subdirs
        # like auto_dream_* and nested paths like reports/researcher/report_id/).
        # Sort newest-first by mtime, take up to 3 distinct archives.
        archives: list[dict] = []
        all_archive_files = sorted(
            ku_dir.rglob("archive_v*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        seen_parents: set = set()
        for archive_file in all_archive_files:
            parent = archive_file.parent
            if parent in seen_parents:
                continue  # already loaded the latest for this conversation
            seen_parents.add(parent)
            try:
                with open(archive_file, encoding="utf-8") as f:
                    archives.append(json.load(f))
            except Exception:
                continue
            if len(archives) >= 3:
                break

        lines: list[str] = []
        for archive in archives:
            for ku in archive.get("knowledge_units", []):
                meaning = (ku.get("core_meaning") or "").strip()
                quote = (ku.get("quote") or "").strip()
                if not meaning:
                    continue
                entry = f"• {meaning}"
                if quote and quote != meaning:
                    entry += f' ("{quote[:MAX_KU_QUOTE_CHARS]}")'
                lines.append(entry)
                if len(lines) >= MAX_KU_ITEMS:
                    break
            if len(lines) >= MAX_KU_ITEMS:
                break

        if not lines:
            return ""
        return "## Knowledge from my recent research:\n" + "\n".join(lines)

    def _load_recent_activity(self, max_tasks: int = 10) -> str:
        """
        Load this role's recent completed/failed tasks from the scheduler
        and format them as a context block so the role can answer questions
        like 'what did you do today' accurately.
        """
        tasks_file = Path(get_memory_subpath("scheduler_tasks.json"))
        if not tasks_file.exists():
            return ""
        try:
            with open(tasks_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return ""

        task_map: Dict = data.get("tasks", data) if isinstance(data, dict) else {}
        if not isinstance(task_map, dict):
            return ""

        # Filter to this role's non-dreaming tasks, sort newest first
        role_tasks = []
        for t in task_map.values():
            if not isinstance(t, dict):
                continue
            if t.get("config", {}).get("role_id") != self.role_id:
                continue
            if t.get("type") in ("dreaming",):
                continue
            completed = t.get("completed_at") or t.get("started_at")
            if not completed:
                continue
            role_tasks.append((completed, t))

        role_tasks.sort(key=lambda x: x[0], reverse=True)

        lines: list[str] = []
        for _, t in role_tasks[:max_tasks]:
            status = t.get("status", "unknown")
            goal = (t.get("config", {}).get("goal") or "").strip()
            goal_short = goal[:120] + ("…" if len(goal) > 120 else "")
            completed = (t.get("completed_at") or t.get("started_at") or "")[:16]
            # Grab a one-line summary from final_answer if available
            final = (
                (t.get("result") or {}).get("metrics", {}).get("final_answer") or ""
            ).strip()
            summary = final[:160] + ("…" if len(final) > 160 else "") if final else ""
            entry = f"• [{completed}] ({status}) {goal_short}"
            if summary:
                entry += f"\n  → {summary}"
            lines.append(entry)

        if not lines:
            return ""
        return "## My recent task activity:\n" + "\n".join(lines)

    def _search_tasks(
        self,
        query: str = "",
        date_from: str = "",
        date_to: str = "",
        status: str = "",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search this role's task history. Returns structured task records.
        Filters by keyword (goal + final_answer), date range, and status.
        """
        tasks_file = Path(get_memory_subpath("scheduler_tasks.json"))
        if not tasks_file.exists():
            return []
        try:
            with open(tasks_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        task_map: Dict = data.get("tasks", data) if isinstance(data, dict) else {}
        if not isinstance(task_map, dict):
            return []

        limit = min(int(limit or 10), 50)
        query_lower = query.strip().lower() if query else ""

        results = []
        for t in task_map.values():
            if not isinstance(t, dict):
                continue
            if t.get("config", {}).get("role_id") != self.role_id:
                continue
            if t.get("type") in ("dreaming",):
                continue

            # Status filter
            task_status = t.get("status", "")
            if status and task_status != status:
                continue

            # Timestamp for sorting and date filter
            ts = t.get("completed_at") or t.get("started_at") or t.get("created_at") or ""
            if date_from and ts[:10] < date_from[:10]:
                continue
            if date_to and ts[:10] > date_to[:10]:
                continue

            # Keyword filter against goal + final_answer
            if query_lower:
                goal = (t.get("config", {}).get("goal") or "").lower()
                final = ((t.get("result") or {}).get("metrics", {}).get("final_answer") or "").lower()
                if query_lower not in goal and query_lower not in final:
                    continue

            final_answer = ((t.get("result") or {}).get("metrics", {}).get("final_answer") or "").strip()
            results.append({
                "id": t.get("id", ""),
                "status": task_status,
                "timestamp": ts[:19],
                "goal": (t.get("config", {}).get("goal") or "").strip(),
                "summary": final_answer[:300] + ("…" if len(final_answer) > 300 else ""),
                "error": t.get("last_error") or "",
            })

        results.sort(key=lambda x: x["timestamp"], reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------ #
    # Message building                                                     #
    # ------------------------------------------------------------------ #

    def _build_messages(
        self,
        system_prompt: str,
        ku_context: str,
        activity_context: str,
        history: List[Dict],
        user_message: str,
    ) -> List[Dict[str, str]]:
        system_content = system_prompt

        if ku_context:
            system_content += f"\n\n{ku_context}"

        if activity_context:
            system_content += f"\n\n{activity_context}"

        system_content += (
            "\n\n## Mode: direct conversation\n"
            "You are talking directly with the user, not executing a task. "
            "Do NOT accept new task assignments — if the user wants to assign "
            "work, tell them to route it through MoJo (scheduler). "
            "Use your tools to look up information before answering when relevant. "
            "Answer from your personality, knowledge, and research."
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_content}
        ]

        for exchange in history[-MAX_HISTORY_TURNS:]:
            messages.append({"role": "user", "content": exchange["user"]})
            messages.append({"role": "assistant", "content": exchange["assistant"]})

        messages.append({"role": "user", "content": user_message})
        return messages

    # ------------------------------------------------------------------ #
    # Tool definitions & execution                                         #
    # ------------------------------------------------------------------ #

    def _get_chat_tools(self, capabilities: List[str]) -> List[Dict]:
        """Return OpenAI tool definitions allowed in the current mode.

        Intersects the role's capabilities categories with the mode contract's
        allowed_tool_categories so the model only sees tools the mode permits.
        """
        contract = get_mode_contract(self.mode)
        names: List[str] = []
        for category in capabilities:
            if category in contract.allowed_tool_categories:
                names.extend(_CHAT_TOOL_ACCESS.get(category, []))
        return [_TOOL_DEFS[n] for n in names if n in _TOOL_DEFS]

    def _search_knowledge(self, query: str = "", limit: int = 5) -> List[Dict[str, Any]]:
        """
        Search this role's personal knowledge — scoped exclusively to self.role_id.

        Sources (both role-scoped):
          1. ~/.memory/roles/{role_id}/knowledge_units/ — distilled knowledge entries
          2. ~/.memory/task_reports/{task_id}.json where role_id == self.role_id

        Knowledge from other roles is never returned. Each assistant maintains
        their own personal knowledge base independently.
        """
        query_lower = query.strip().lower() if query else ""
        limit = min(int(limit or 5), 20)
        results: List[Dict[str, Any]] = []

        # --- Source 1: role's distilled knowledge units ---
        # Use rglob to handle nested archive paths (reports/, sessions/, flat auto_dream_*)
        ku_dir = Path(get_memory_subpath("roles")) / self.role_id / "knowledge_units"
        if ku_dir.exists():
            all_archives = sorted(
                ku_dir.rglob("archive_v*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            seen_ku_parents: set = set()
            for archive_file in all_archives:
                if len(results) >= limit:
                    break
                parent = archive_file.parent
                if parent in seen_ku_parents:
                    continue
                seen_ku_parents.add(parent)
                try:
                    with open(archive_file, encoding="utf-8") as f:
                        archive = json.load(f)
                except Exception:
                    continue
                for ku in archive.get("knowledge_units", []):
                    meaning = (ku.get("core_meaning") or "").strip()
                    quote = (ku.get("quote") or "").strip()
                    source = (ku.get("source") or "").strip()
                    if not meaning:
                        continue
                    text = meaning + (f' — "{quote}"' if quote and quote != meaning else "")
                    if query_lower and query_lower not in text.lower() and query_lower not in source.lower():
                        continue
                    results.append({
                        "type": "knowledge_unit",
                        "source": source,
                        "content": text,
                        "created_at": (ku.get("created_at") or archive.get("created_at") or "")[:19],
                    })
                    if len(results) >= limit:
                        break

        # --- Source 2: this role's task completion reports ---
        if len(results) < limit:
            reports_dir = Path(get_memory_subpath("task_reports"))
            if reports_dir.exists():
                for report_file in sorted(
                    reports_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
                ):
                    try:
                        with open(report_file, encoding="utf-8") as f:
                            report = json.load(f)
                    except Exception:
                        continue
                    # Enforce role isolation
                    if report.get("role_id") != self.role_id:
                        continue
                    if query_lower:
                        goal = (report.get("goal") or "").lower()
                        content = (report.get("content") or "").lower()
                        summary = (report.get("summary") or "").lower()
                        if query_lower not in goal and query_lower not in content and query_lower not in summary:
                            continue
                    # Prefer v2 summary; fall back to legacy content for old reports
                    snippet = report.get("summary") or report.get("content", "")
                    results.append({
                        "type": "task_report",
                        "task_id": report.get("task_id", ""),
                        "goal": report.get("goal", ""),
                        "status": report.get("status", ""),
                        "created_at": (report.get("created_at") or "")[:19],
                        "content": snippet,
                        "completed": report.get("completed", []),
                        "findings": report.get("findings", []),
                        "schema_version": report.get("schema_version", "v1"),
                    })
                    if len(results) >= limit:
                        break

        return results

    def _routed_tasks(self, args: Dict[str, Any]) -> str:
        """Status and answer of the tasks this role routed for the owner. Read-only; only those tasks."""
        tasks_file = Path(get_memory_subpath("scheduler_tasks.json"))
        if not tasks_file.exists():
            return json.dumps({"success": False, "error": "no scheduler task file"})
        try:
            data = json.loads(tasks_file.read_text(encoding="utf-8"))
        except Exception as e:
            return json.dumps({"success": False, "error": f"could not read the task file: {e}"})
        task_map = data.get("tasks", data) if isinstance(data, dict) else {}
        mine = [t for t in task_map.values() if isinstance(t, dict)
                and ((t.get("config") or {}).get("origin") or {}).get("via") == self.role_id]
        wanted = (args.get("task_id") or "").strip()
        if wanted:
            mine = [t for t in mine if t.get("id") == wanted]
        mine.sort(key=lambda t: t.get("created_at") or "", reverse=True)
        rows = []
        for t in mine[: 1 if wanted else min(int(args.get("limit") or 5), 20)]:
            answer = (((t.get("result") or {}).get("metrics") or {}).get("final_answer") or "").strip()
            rows.append({
                "task_id": t.get("id"),
                "assistant": (t.get("config") or {}).get("role_id"),
                "status": t.get("status"),
                "created_at": (t.get("created_at") or "")[:19],
                "completed_at": (t.get("completed_at") or "")[:19],
                "waiting_on": t.get("pending_question") if t.get("status") == "waiting_for_input" else None,
                "error": t.get("last_error") or None,
                "answer": answer[: 4000 if wanted else 600] or None,
            })
        return json.dumps({"success": True, "count": len(rows), "tasks": rows}, ensure_ascii=False)

    def _route_to_role(self, args: Dict[str, Any]) -> str:
        """Create a scheduler task for another role from the owner's message. Fails with a reason; no substitute role."""
        from app.scheduler.models import Task, TaskPriority, TaskResources, TaskType
        from app.scheduler.spec_qualifier import classify_goal

        def fail(msg: str, **extra) -> str:
            return json.dumps({"success": False, "error": msg, **extra}, ensure_ascii=False)

        target = (args.get("role_id") or "").strip()
        message = (args.get("message") or "").strip()
        if not target or not message:
            return fail("role_id and message are required")
        if self._scheduler is None:
            return fail("the scheduler is not available in this channel, so nothing was sent")
        known = [r["id"] for r in RoleManager().list_roles() if r.get("id")]
        allowed = [r for r in (self._routable_roles if self._routable_roles is not None else known)
                   if r != self.role_id]
        if target not in known or target not in allowed:
            return fail(f"cannot route to {target!r}", available=[r for r in allowed if r in known])
        goal = (
            f"Owner request, sent from the owner's phone through {self.role_id} (their personal assistant):\n"
            f'"""\n{message}\n"""\n'
            "Scope: handle this within your own role. If it belongs to another role, say which one instead of doing it.\n"
            "Done when: you have replied to the owner with a clear answer or plan, or asked the owner one specific question.\n"
            "Verify by: re-reading the request and checking that every point it raised is addressed in your reply."
        )
        spec = classify_goal(goal)
        if not spec.passed:
            return fail("spec_quality_gate", missing=spec.missing, feedback=spec.feedback)
        task_id = f"owner_route_{target}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        task = Task(
            id=task_id,
            type=TaskType.INTERNAL_ASSIGNMENT,
            priority=TaskPriority.MEDIUM,
            config={"goal": goal, "role_id": target,
                    "origin": {"channel": "owner_hub", "via": self.role_id, "session_id": self.session_id}},
            # The 300 s scheduler default is too short for 10 rounds on a local model (~50 s each):
            # a routed task died at 313 s after 6 rounds with no answer.
            resources=TaskResources(max_iterations=10, max_duration_seconds=ROUTED_TASK_MAX_SECONDS),
            created_by="user",  # the owner's own request: completion notifies the owner
        )
        if not self._scheduler.add_task(task):
            return fail(f"scheduler refused task {task_id} (id may already exist)")
        logger.info("[role_chat] %s routed an owner request to %s as %s", self.role_id, target, task_id)
        return json.dumps({"success": True, "task_id": task_id, "role_id": target}, ensure_ascii=False)

    async def _execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Execute a single chat tool and return its result as a JSON string."""
        # knowledge_search and task_search are handled locally
        if name == "knowledge_search":
            try:
                results = self._search_knowledge(
                    query=args.get("query", ""),
                    limit=args.get("limit", 5),
                )
                return json.dumps(
                    {"success": True, "count": len(results), "reports": results},
                    ensure_ascii=False,
                )
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        # memory_search is scoped to this role's knowledge — never user personal memory
        if name == "memory_search":
            try:
                results = self._search_knowledge(
                    query=args.get("query", ""),
                    limit=args.get("max_items", args.get("limit", 5)),
                )
                return json.dumps(
                    {"success": True, "count": len(results), "results": results},
                    ensure_ascii=False,
                )
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        # task_search is handled locally — no external registry needed
        if name == "task_search":
            try:
                results = self._search_tasks(
                    query=args.get("query", ""),
                    date_from=args.get("date_from", ""),
                    date_to=args.get("date_to", ""),
                    status=args.get("status", ""),
                    limit=args.get("limit", 10),
                )
                return json.dumps({"success": True, "count": len(results), "tasks": results}, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})

        if name == "route_to_role":
            return self._route_to_role(args)
        if name == "routed_tasks":
            return self._routed_tasks(args)

        # refer_to_role — cross-role referral
        if name == "refer_to_role":
            target_role_id = args.get("role_id", "")
            reason = args.get("reason", "")
            context_summary = args.get("context_summary", "")

            # Verify the target role exists
            rm = RoleManager()
            target_role = rm.get(target_role_id)
            if not target_role:
                return json.dumps({
                    "success": False,
                    "error": f"Role '{target_role_id}' not found. Available roles: {[r['id'] for r in rm.list_roles()]}",
                })

            # Return a structured referral response
            referral = {
                "success": True,
                "type": "referral",
                "referral_to": target_role_id,
                "referral_reason": reason,
                "context_summary": context_summary,
                "message": (
                    f"I'm referring you to {target_role.get('name', target_role_id)} — "
                    f"{reason}. "
                    f"Start a new chat with {target_role_id} for a better answer."
                ),
            }
            return json.dumps(referral, ensure_ascii=False)

        try:
            from app.scheduler.capability_registry import CapabilityRegistry
            from app.services.memory_backend import create_memory_service

            registry = CapabilityRegistry()
            registry.set_memory_service(create_memory_service())
            registry.set_task_context(task_id=None, dispatch_depth=0, role_id=self.role_id)
            result = await registry.execute_tool(name, args)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[role_chat] tool '{name}' failed: {e}")
            return json.dumps({"success": False, "error": str(e)})

    # ------------------------------------------------------------------ #
    # LLM call (returns raw response dict)                                 #
    # ------------------------------------------------------------------ #

    async def _call_raw(
        self,
        messages: List[Dict],
        rm: Any,
        tools: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Call the LLM via ResourceManager and return the full response dict, with the answering
        resource under "_resource" / "_model". Raises when no resource is available or the call
        fails -- no retry on another tier, so the failure is visible and can be fixed.
        """
        import httpx
        from app.llm.unified_client import UnifiedLLMClient

        scope = self._max_data_scope
        resource = rm.acquire(max_data_scope=scope)
        if resource is None:
            inside = [r for r in rm.selection_order(max_data_scope=scope) if r["data_scope"] and not (r["excluded_because"] or "").startswith("data scope")]
            detail = "; ".join(f"{r['id']}: {r['excluded_because']}" for r in inside if not r["eligible"])[:500]
            raise RuntimeError(
                "no LLM resource available" + (f" within data scope {scope}" if scope else "")
                + (f" ({detail})" if detail else "")
            )

        # Resolve dynamic model for local servers (model=None + dynamic_discovery)
        model = resource.model
        if not model and resource.base_url:
            try:
                base = resource.base_url.rstrip("/")
                headers = {}
                if resource.api_key:
                    headers["Authorization"] = f"Bearer {resource.api_key}"
                async with httpx.AsyncClient(timeout=5.0) as c:
                    resp = await c.get(f"{base}/models", headers=headers)
                    if resp.status_code == 200:
                        first = (resp.json().get("data") or [{}])[0]
                        model = first.get("id") or ""
            except Exception:
                pass

        def _make_config(r, m):
            return {
                "base_url": r.base_url,
                "model": m,
                "api_key": r.api_key,
                "output_limit": min(r.output_limit or 8192, 8192),
                "message_format": "openai",
                "provider": r.provider,
            }

        client = UnifiedLLMClient()
        try:
            # One request at a time per local model: wait in line (bounded), then call.
            async with rm.slot(resource.id, max_wait_s=CHAT_QUEUE_WAIT_MAX_SECONDS):
                _t0 = time.time()
                try:
                    data = await client.call_async(
                        messages=messages,
                        resource_config=_make_config(resource, model),
                        model_override=model,
                        tools=tools or None,
                    )
                except Exception as e:
                    rm.record_usage(resource.id, success=False, task_class="chat.role",
                                    duration_ms=(time.time() - _t0) * 1000)
                    raise RuntimeError(f"resource '{resource.id}' failed: {type(e).__name__}: {e}") from e
        except ResourceBusyError as e:
            # Not a fault of the resource: nothing is recorded against it.
            raise RuntimeError(f"{e}; the model is busy with other work, try again shortly") from e
        rm.record_usage(resource.id, success=True, token_usage=data.get("usage"), model_served=data.get("_selected_model") or model,
                        duration_ms=(time.time() - _t0) * 1000, task_class="chat.role")
        data["_resource"] = resource.id
        data["_model"] = model
        return data

    async def _call_via_llm_interface(self, messages: List[Dict]) -> str:
        """Fallback when no ResourceManager available — collapses to single prompt."""
        from app.llm.llm_interface import LLMInterface

        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        turns = [m for m in messages if m["role"] != "system"]
        history_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in turns
            if isinstance(m.get("content"), str)
        )
        llm = LLMInterface()
        return llm.generate_response(history_text, context=system)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def exchange(
        self,
        message: str,
        resource_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Send a message and get a response from the role.

        Runs up to MAX_CHAT_ITERATIONS to allow the role to call tools
        (memory_search, web_search, fetch_url) before giving its final answer.

        Returns:
            {role_id, session_id, response, context_used: {knowledge_units, history_turns, tool_calls}}
        """
        role = RoleManager().get(self.role_id)
        if role is None:
            return {
                "error": f"Role '{self.role_id}' not found",
                "session_id": self.session_id,
            }

        base_prompt = role.get(
            "system_prompt", f"You are {role.get('name', self.role_id)}."
        )
        # Resolve mode overlay: role-specific override > contract default.
        # Prepend at highest priority (model reads top-down) and strip any
        # tool-instruction sections that describe tools unavailable in this mode.
        contract = get_mode_contract(self.mode)
        role_overlay = (role.get("mode_overlays") or {}).get(self.mode.value)
        mode_overlay = role_overlay if role_overlay else contract.prompt_overlay
        ninechapter_overlay = build_behavioral_overlay(role)
        system_prompt = mode_overlay + ninechapter_overlay + _strip_tool_sections(base_prompt)
        _owner_fields = role.get("owner_context_fields") if role else None
        _owner_slice = build_owner_context_slice(load_owner_profile(), "minimal", _owner_fields)
        if _owner_slice:
            system_prompt = system_prompt + _owner_slice

        session = self._load_session()
        ku_context = self._load_ku_context()
        activity_context = self._load_recent_activity()
        ku_count = ku_context.count("•") if ku_context else 0
        history = session.get("exchanges", [])

        messages = self._build_messages(system_prompt, ku_context, activity_context, history, message)

        capabilities = role.get("capabilities") or []
        chat_tools = self._get_chat_tools(capabilities) if resource_manager else []

        response = ""
        total_tool_calls = 0
        answered_by: Dict[str, Any] = {}

        try:
            if resource_manager is not None:
                msg: Dict[str, Any] = {}
                for _iteration in range(MAX_CHAT_ITERATIONS):
                    data = await self._call_raw(
                        messages, resource_manager,
                        tools=chat_tools if chat_tools else None,
                    )
                    answered_by = {"resource": data.get("_resource"), "model": data.get("_model")}
                    msg = (data.get("choices") or [{}])[0].get("message") or {}
                    tool_calls = msg.get("tool_calls")

                    if not tool_calls:
                        # Final response — extract text (strip think tokens if present)
                        content = msg.get("content") or ""
                        if "<think>" in content and "</think>" in content:
                            after = content.split("</think>", 1)[-1].strip()
                            content = after if after else content
                        response = content
                        break

                    # Append assistant tool-call message and execute each tool
                    messages.append(msg)
                    for tc in tool_calls:
                        fn = tc.get("function") or {}
                        tool_name = fn.get("name", "")
                        raw_args = fn.get("arguments") or "{}"
                        try:
                            args = json.loads(raw_args)
                        except Exception:
                            snippet = raw_args[:120]
                            parse_error = (
                                f"Tool arguments could not be parsed as JSON: {snippet!r}. "
                                "Please retry with valid JSON."
                            )
                            logger.warning(
                                f"[role_chat] malformed tool args for '{tool_name}': {snippet!r}"
                            )
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.get("id", ""),
                                "content": json.dumps({"success": False, "error": parse_error}),
                            })
                            total_tool_calls += 1
                            continue
                        logger.debug(f"[role_chat] tool call: {tool_name}({args})")
                        result_str = await self._execute_tool(tool_name, args)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": result_str,
                        })
                        total_tool_calls += 1
                else:
                    # Tool loops consumed the full budget. Force one final text-only answer.
                    # A user turn, not a system one: chat templates (Ornith/Qwen) reject a system
                    # message anywhere but first, and the request fails with a 500 from the server.
                    messages.append({
                        "role": "user",
                        "content": _FINAL_TOOL_LOOP_PROMPT,
                    })
                    final_data = await self._call_raw(
                        messages,
                        resource_manager,
                        tools=None,
                    )
                    final_msg = (final_data.get("choices") or [{}])[0].get("message") or {}
                    content = final_msg.get("content") or msg.get("content") or ""
                    if "<think>" in content and "</think>" in content:
                        after = content.split("</think>", 1)[-1].strip()
                        content = after if after else content
                    if not content.strip():
                        # An error, not an answer: a substitute string would be shown as the
                        # role's reply and saved into its history for dreaming to learn from.
                        raise RuntimeError(
                            f"{self.role_id} produced no answer after {MAX_CHAT_ITERATIONS} tool rounds"
                        )
                    response = content
            else:
                response = await self._call_via_llm_interface(messages)

        except Exception as e:
            # Not saved: an error is not an answer, and saved exchanges become memory via dreaming.
            logger.error(f"RoleChatSession.exchange failed for {self.role_id}: {e}")
            return {"error": str(e), "role_id": self.role_id, "session_id": self.session_id}

        response = _ensure_response_quality(response, role_name=role.get("name", self.role_id))
        self._save_session(session, message, response)

        return {
            "role_id": self.role_id,
            "session_id": self.session_id,
            "response": response,
            **answered_by,
            "context_used": {
                "knowledge_units": ku_count,
                "history_turns": len(history),
                "tool_calls": total_tool_calls,
            },
        }


    async def exchange_stream(
        self,
        message: str,
        resource_manager: Optional[Any] = None,
    ) -> AsyncIterator[str]:
        """
        Streaming variant of exchange().

        Yields SSE-formatted lines:
          data: {"type": "tool",  "name": "<tool_name>"}      — tool call in progress
          data: {"type": "token", "text": "<chunk>"}           — LLM text token
          data: {"type": "done",  "session_id": "...", "tool_calls": N}  — complete

        Tool-call iterations run to completion before streaming begins.
        Only the final text response is streamed token-by-token.
        """
        role = RoleManager().get(self.role_id)
        if role is None:
            yield f'data: {json.dumps({"type": "error", "message": f"Role {self.role_id!r} not found"})}\n\n'
            return

        base_prompt = role.get(
            "system_prompt", f"You are {role.get('name', self.role_id)}."
        )
        contract = get_mode_contract(self.mode)
        role_overlay = (role.get("mode_overlays") or {}).get(self.mode.value)
        mode_overlay = role_overlay if role_overlay else contract.prompt_overlay
        ninechapter_overlay = build_behavioral_overlay(role)
        system_prompt = mode_overlay + ninechapter_overlay + _strip_tool_sections(base_prompt)
        _owner_fields = role.get("owner_context_fields") if role else None
        _owner_slice = build_owner_context_slice(load_owner_profile(), "minimal", _owner_fields)
        if _owner_slice:
            system_prompt = system_prompt + _owner_slice

        session = self._load_session()
        ku_context = self._load_ku_context()
        activity_context = self._load_recent_activity()
        history = session.get("exchanges", [])

        messages = self._build_messages(system_prompt, ku_context, activity_context, history, message)

        capabilities = role.get("capabilities") or []
        chat_tools = self._get_chat_tools(capabilities) if resource_manager else []

        total_tool_calls = 0
        response_text = ""

        try:
            if resource_manager is None:
                # No resource manager — fall back to blocking LLM interface
                response_text = await self._call_via_llm_interface(messages)
                for chunk in _split_chunks(response_text):
                    yield f'data: {json.dumps({"type": "token", "text": chunk})}\n\n'
            else:
                # --- Streaming tool-call loop ---
                from app.llm.unified_client import UnifiedLLMClient
                client = UnifiedLLMClient()

                for _iteration in range(MAX_CHAT_ITERATIONS):
                    resource = resource_manager.acquire(max_data_scope=self._max_data_scope)
                    if resource is None:
                        err = "(No LLM resource available)"
                        yield f'data: {json.dumps({"type": "token", "text": err})}\n\n'
                        response_text = err
                        break

                    model = resource.model or ""
                    resource_config = {
                        "base_url": resource.base_url,
                        "model": model,
                        "api_key": resource.api_key,
                        "output_limit": min(resource.output_limit or 8192, 8192),
                        "message_format": "openai",
                        "provider": resource.provider,
                    }

                    # Stream content tokens immediately; accumulate tool calls
                    content_buf = ""
                    tool_calls_received = None
                    try:
                        async for event in client.call_stream_async(
                            messages, resource_config,
                            model_override=model,
                            tools=chat_tools if chat_tools else None,
                        ):
                            if event["type"] == "content":
                                text = event["text"]
                                # Strip <think> prefix before streaming
                                if not content_buf and text.startswith("<think>"):
                                    continue
                                content_buf += text
                                yield f'data: {json.dumps({"type": "token", "text": text})}\n\n'
                            elif event["type"] == "tool_calls":
                                tool_calls_received = event["tool_calls"]
                    except Exception as stream_err:
                        logger.warning(f"[role_chat] stream failed: {stream_err}")
                        # Surface a client-visible status token immediately so the
                        # browser gets bytes right away, then send periodic SSE
                        # keepalive comments while the blocking fallback call runs.
                        # Without this, the connection goes fully silent for the
                        # entire fallback duration -- this exact silence (zero
                        # bytes during a slow blocking call) is what produced
                        # "Error: network error" client-side when call_stream_async
                        # broke (see the httpx.AsyncClient timeout kwarg bug fixed
                        # 2026-08). That one trigger is fixed, but this fallback
                        # path itself still exists for any future streaming failure,
                        # so it needs to stop going silent regardless of cause.
                        yield f'data: {json.dumps({"type": "status", "message": "Stream interrupted, retrying..."})}\n\n'
                        fallback_task = asyncio.create_task(
                            self._call_raw(messages, resource_manager, tools=chat_tools)
                        )
                        while not fallback_task.done():
                            done, _ = await asyncio.wait(
                                {fallback_task}, timeout=STREAM_FALLBACK_KEEPALIVE_INTERVAL
                            )
                            if not done:
                                yield ": keepalive\n\n"
                        fallback_data = await fallback_task
                        fallback_msg = (fallback_data.get("choices") or [{}])[0].get("message") or {}
                        tool_calls_received = fallback_msg.get("tool_calls")
                        if not tool_calls_received:
                            content_buf = fallback_msg.get("content") or ""
                            for chunk in _split_chunks(content_buf):
                                yield f'data: {json.dumps({"type": "token", "text": chunk})}\n\n'

                    # If no tool calls, we're done
                    if not tool_calls_received:
                        response_text = content_buf
                        break

                    # Execute tool calls
                    msg = {
                        "role": "assistant",
                        "content": content_buf or None,
                        "tool_calls": tool_calls_received,
                    }
                    messages.append(msg)
                    for tc in tool_calls_received:
                        fn = tc.get("function") or {}
                        tool_name = fn.get("name", "")
                        yield f'data: {json.dumps({"type": "tool", "name": tool_name})}\n\n'
                        raw_args = fn.get("arguments") or "{}"
                        try:
                            args = json.loads(raw_args)
                        except Exception:
                            snippet = raw_args[:120]
                            parse_error = (
                                f"Tool arguments could not be parsed as JSON: {snippet!r}. "
                                "Please retry with valid JSON."
                            )
                            logger.warning(
                                f"[role_chat] malformed tool args for '{tool_name}': {snippet!r}"
                            )
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.get("id", ""),
                                "content": json.dumps({"success": False, "error": parse_error}),
                            })
                            total_tool_calls += 1
                            continue
                        result_str = await self._execute_tool(tool_name, args)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": result_str,
                        })
                        total_tool_calls += 1
                else:
                    # Budget exhausted — force a final text-only call
                    messages.append({"role": "user", "content": _FINAL_TOOL_LOOP_PROMPT})  # not system: templates allow it only first
                    resource = resource_manager.acquire(max_data_scope=self._max_data_scope)
                    if resource:
                        model = resource.model or ""
                        resource_config = {
                            "base_url": resource.base_url,
                            "model": model,
                            "api_key": resource.api_key,
                            "output_limit": min(resource.output_limit or 8192, 8192),
                            "message_format": "openai",
                            "provider": resource.provider,
                        }
                        async for event in client.call_stream_async(
                            messages, resource_config, model_override=model
                        ):
                            if event["type"] == "content":
                                text = event["text"]
                                if not response_text and text.startswith("<think>"):
                                    continue
                                response_text += text
                                yield f'data: {json.dumps({"type": "token", "text": text})}\n\n'
                    if not response_text.strip():
                        raise RuntimeError(
                            f"{self.role_id} produced no answer after {MAX_CHAT_ITERATIONS} tool rounds"
                        )

        except Exception as exc:
            err_msg = str(exc)
            logger.error(f"RoleChatSession.exchange_stream failed for {self.role_id}: {err_msg}")
            err = f"(Error: {err_msg})"
            yield f'data: {json.dumps({"type": "token", "text": err})}\n\n'
            response_text = err

        # Apply the same quality gate as the non-streaming path.
        # If the raw streamed text is hollow/empty, emit a corrective token
        # and save the corrected text instead of the bad output.
        quality_checked = _ensure_response_quality(
            response_text, role_name=role.get("name", self.role_id)
        )
        if quality_checked != response_text:
            yield f'data: {json.dumps({"type": "token", "text": quality_checked})}\n\n'
            response_text = quality_checked

        self._save_session(session, message, response_text)

        yield f'data: {json.dumps({"type": "done", "session_id": self.session_id, "tool_calls": total_tool_calls})}\n\n'


def _split_chunks(text: str, size: int = 4) -> List[str]:
    """Split a complete text string into small chunks for simulated streaming."""
    return [text[i:i + size] for i in range(0, len(text), size)] if text else []


def list_chat_sessions(role_id: str) -> List[Dict[str, Any]]:
    """Return summary of all chat sessions for a role, newest first."""
    session_dir = (
        Path(get_memory_subpath("roles")) / role_id / "chat_history"
    )
    if not session_dir.exists():
        return []

    sessions = []
    for f in sorted(session_dir.glob("*.json"), reverse=True):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            sessions.append({
                "session_id": data.get("session_id"),
                "started_at": data.get("started_at"),
                "last_active": data.get("last_active"),
                "turn_count": len(data.get("exchanges", [])),
            })
        except Exception:
            continue
    return sessions
