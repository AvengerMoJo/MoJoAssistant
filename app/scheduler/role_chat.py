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

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from app.config.paths import get_memory_subpath
from app.roles.role_manager import RoleManager
from app.scheduler.interaction_mode import InteractionMode, get_mode_contract
from app.scheduler.ninechapter import build_behavioral_overlay
from app.roles.owner_context import load_owner_profile, build_owner_context_slice

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 10    # conversation turns carried into context
MAX_KU_ITEMS = 8          # knowledge units injected as context
MAX_KU_QUOTE_CHARS = 200  # truncate long KU quotes
MAX_CHAT_ITERATIONS = 5   # max tool-call iterations per exchange

# Maps tool catalog categories → concrete tool names available in chat mode.
# Filtered at runtime by the active mode contract's allowed_tool_categories.
_CHAT_TOOL_ACCESS: Dict[str, List[str]] = {
    "memory": ["memory_search", "task_search"],
    "knowledge": ["knowledge_search"],
}

# OpenAI-format tool definitions for each supported chat tool
_TOOL_DEFS: Dict[str, Dict] = {
    "memory_search": {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": (
                "Search your memory for relevant information, past conversations, "
                "documents, and knowledge."
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

    def __init__(
        self,
        role_id: str,
        session_id: Optional[str] = None,
        mode: InteractionMode = InteractionMode.DASHBOARD_CHAT,
    ):
        self.role_id = role_id
        self.mode = mode
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
        return {
            "session_id": self.session_id,
            "role_id": self.role_id,
            "started_at": datetime.now().isoformat(),
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

        archives: list[dict] = []
        for subdir in sorted(ku_dir.iterdir(), reverse=True):
            if not subdir.is_dir():
                continue
            archive_files = sorted(subdir.glob("archive_v*.json"), reverse=True)
            if archive_files:
                try:
                    with open(archive_files[0], encoding="utf-8") as f:
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
        ku_dir = Path(get_memory_subpath("roles")) / self.role_id / "knowledge_units"
        if ku_dir.exists():
            for subdir in sorted(ku_dir.iterdir(), reverse=True):
                if not subdir.is_dir():
                    continue
                archive_files = sorted(subdir.glob("archive_v*.json"), reverse=True)
                for archive_file in archive_files[:1]:
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

        try:
            from app.scheduler.dynamic_tool_registry import DynamicToolRegistry
            from app.services.memory_service import MemoryService

            registry = DynamicToolRegistry()
            registry.set_memory_service(MemoryService())
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
        Call the LLM via ResourceManager and return the full response dict.
        Falls back to FREE_API tier if the primary resource returns an error.
        """
        import httpx
        from app.llm.unified_client import UnifiedLLMClient

        resource = rm.acquire()
        if resource is None:
            return {"choices": [{"message": {"content": "(No LLM resource available.)"}}]}

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
            data = await client.call_async(
                messages=messages,
                resource_config=_make_config(resource, model),
                model_override=model,
                tools=tools or None,
            )
            rm.record_usage(resource.id, success=True)
            return data
        except Exception as e:
            rm.record_usage(resource.id, success=False)
            logger.warning(
                f"[role_chat] resource '{resource.id}' failed ({type(e).__name__}: {e}); "
                "trying free_api tier fallback"
            )

        try:
            from app.scheduler.resource_pool import ResourceTier
            fallback = rm.acquire(tier_preference=[ResourceTier.FREE_API])
        except Exception:
            fallback = None

        if fallback is None:
            return {"choices": [{"message": {"content": f"(LLM unavailable: {e})"}}]}

        try:
            data = await client.call_async(
                messages=messages,
                resource_config=_make_config(fallback, fallback.model),
                model_override=fallback.model,
                tools=tools or None,
            )
            rm.record_usage(fallback.id, success=True)
            return data
        except Exception as e2:
            rm.record_usage(fallback.id, success=False)
            return {"choices": [{"message": {"content": f"(LLM unavailable: {e2})"}}]}

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
        _owner_slice = build_owner_context_slice(load_owner_profile(), "minimal")
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

        try:
            if resource_manager is not None:
                msg: Dict[str, Any] = {}
                for _iteration in range(MAX_CHAT_ITERATIONS):
                    data = await self._call_raw(
                        messages, resource_manager,
                        tools=chat_tools if chat_tools else None,
                    )
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
                    messages.append({
                        "role": "system",
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
                    response = content or "(No response after tool loop)"
            else:
                response = await self._call_via_llm_interface(messages)

        except Exception as e:
            logger.error(f"RoleChatSession.exchange failed for {self.role_id}: {e}")
            response = f"(Error generating response: {e})"

        response = _ensure_response_quality(response, role_name=role.get("name", self.role_id))
        self._save_session(session, message, response)

        return {
            "role_id": self.role_id,
            "session_id": self.session_id,
            "response": response,
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
        _owner_slice = build_owner_context_slice(load_owner_profile(), "minimal")
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
                # --- Tool-call iterations (non-streaming) ---
                msg: Dict[str, Any] = {}
                ready_to_stream = False
                for _iteration in range(MAX_CHAT_ITERATIONS):
                    data = await self._call_raw(
                        messages, resource_manager,
                        tools=chat_tools if chat_tools else None,
                    )
                    msg = (data.get("choices") or [{}])[0].get("message") or {}
                    tool_calls = msg.get("tool_calls")

                    if not tool_calls:
                        # No more tool calls — stream this response
                        ready_to_stream = True
                        break

                    # Execute tools, yield status events so the UI shows progress
                    messages.append(msg)
                    for tc in tool_calls:
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
                    # Budget exhausted — force a final text-only call, then stream it
                    messages.append({"role": "system", "content": _FINAL_TOOL_LOOP_PROMPT})
                    ready_to_stream = True

                # --- Stream the final text response ---
                if ready_to_stream and msg.get("tool_calls") is None and msg.get("content"):
                    # Non-streaming final response already in `msg` (no tool calls, got text)
                    content = msg.get("content") or ""
                    if "<think>" in content and "</think>" in content:
                        content = content.split("</think>", 1)[-1].strip() or content
                    response_text = content
                    for chunk in _split_chunks(response_text):
                        yield f'data: {json.dumps({"type": "token", "text": chunk})}\n\n'
                else:
                    # Use streaming for the final LLM call
                    resource = resource_manager.acquire()
                    if resource is None:
                        err = "(No LLM resource available for streaming)"
                        yield f'data: {json.dumps({"type": "token", "text": err})}\n\n'
                        response_text = err
                    else:
                        model = resource.model or ""
                        resource_config = {
                            "base_url": resource.base_url,
                            "model": model,
                            "api_key": resource.api_key,
                            "output_limit": min(resource.output_limit or 8192, 8192),
                            "message_format": "openai",
                            "provider": resource.provider,
                        }
                        from app.llm.unified_client import UnifiedLLMClient
                        client = UnifiedLLMClient()
                        try:
                            async for chunk in client.call_stream_async(
                                messages, resource_config, model_override=model
                            ):
                                # Strip <think> prefix before streaming
                                if not response_text and chunk.startswith("<think>"):
                                    continue
                                response_text += chunk
                                yield f'data: {json.dumps({"type": "token", "text": chunk})}\n\n'
                            # Post-process: strip any <think>...</think> block
                            if "<think>" in response_text and "</think>" in response_text:
                                response_text = response_text.split("</think>", 1)[-1].strip()
                        except Exception as stream_err:
                            logger.warning(f"[role_chat] stream failed, falling back: {stream_err}")
                            # Fallback to blocking call
                            fallback_data = await self._call_raw(messages, resource_manager, tools=None)
                            fallback_msg = (fallback_data.get("choices") or [{}])[0].get("message") or {}
                            content = fallback_msg.get("content") or ""
                            if "<think>" in content and "</think>" in content:
                                content = content.split("</think>", 1)[-1].strip() or content
                            response_text = content
                            for chunk in _split_chunks(response_text):
                                yield f'data: {json.dumps({"type": "token", "text": chunk})}\n\n'

        except Exception as e:
            logger.error(f"RoleChatSession.exchange_stream failed for {self.role_id}: {e}")
            err = f"(Error: {e})"
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
