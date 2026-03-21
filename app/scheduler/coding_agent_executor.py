"""
CodingAgentExecutor

Drives a coding agent role (e.g. Popo) using a local LLM to orchestrate
an external coding agent (OpenCode, Claude Code).

Architecture (three tiers):
  Tier 1  — local LLM (e.g. qwen3.5-35b-a3b) prompted as the role personality
  Tier 2  — OpenCodeBackend (coding-agent-mcp-tool submodule) — all HTTP API details
  Tier 3  — this file — orchestration, permission bridging, HITL routing

See docs/architecture/MCP_DESIGN.md §16 for the full architectural rationale.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from datetime import datetime
from typing import Any

from app.scheduler.models import Task, TaskResult
from app.scheduler.resource_pool import ResourceManager
from app.scheduler.session_storage import SessionMessage, SessionStorage, TaskSession

logger = logging.getLogger(__name__)

# Tool definitions exposed to the orchestrating LLM
_CODING_AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "agent_send_message",
            "description": (
                "Send an instruction to the coding agent and wait for it to respond. "
                "The agent has shell access, can read/write files, run tests, and use tools. "
                "The response will include what the agent did and any output it produced."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "Clear instruction for the coding agent to execute",
                    }
                },
                "required": ["instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agent_get_messages",
            "description": (
                "Get the full conversation history of the current agent session, "
                "including all messages and tool outputs so far. Use this to understand "
                "the current state when resuming after an interruption."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Pause and ask the user a question. Use this only when you genuinely "
                "cannot proceed without a human decision — not to report status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The specific question for the user",
                    }
                },
                "required": ["question"],
            },
        },
    },
]

CONTINUE_PROMPT = (
    "Continue working toward the goal. "
    "If you are done, provide your answer inside <FINAL_ANSWER> tags."
)

NEAR_LIMIT_PROMPT = (
    "⚠ ITERATION BUDGET WARNING: You are on iteration {current} of {max} — "
    "only {remaining} iteration(s) left.\n\n"
    "You MUST stop using tools and produce a <FINAL_ANSWER> NOW.\n\n"
    "Summarise: what was accomplished, what remains, and any open issues. "
    "Do NOT call any more tools."
)


class CodingAgentExecutor:
    """
    Executes coding agent tasks by driving a local LLM (the role's persona)
    to orchestrate an external coding agent (OpenCode, Claude Code).

    Permission requests from the coding agent are bridged to the MoJo HITL inbox.
    """

    def __init__(
        self,
        resource_manager: ResourceManager,
        logger: Any = None,
        memory_service: Any = None,
    ) -> None:
        self._rm = resource_manager
        self._logger = logger
        self._memory_service = memory_service
        self._session_storage = SessionStorage()
        self._registry: Any = None  # BackendRegistry — lazy-loaded and cached

    def _log(self, msg: str, level: str = "info") -> None:
        if self._logger:
            getattr(self._logger, level)(f"[CodingAgentExecutor] {msg}")

    # ------------------------------------------------------------------ #
    #  Entry point                                                         #
    # ------------------------------------------------------------------ #

    async def execute(self, task: Task) -> TaskResult:
        """
        Run the coding agent loop for a task.

        Task config keys:
            goal (str): What the role should accomplish.
            role_id (str): Which role to load (must have executor="coding_agent").
            server_id (str, optional): Override the role's default server_id.
            resume_from_task_id (str, optional): Resume a previous LLM session.
            reply_to_question (str, optional): User reply injected after WAITING_FOR_INPUT.

        Session and permission state are owned by BackendRegistry (coding-agent-mcp-tool).
        MoJo never stores session IDs or permission handles in task.config.
        """
        self._waiting_for_input_question: str | None = None
        self._pending_permission: dict | None = None

        config = task.config or {}
        goal = config.get("goal", "")
        if not goal:
            return TaskResult(success=False, error_message="Missing 'goal' in task config")

        role_id = config.get("role_id")
        role = self._load_role(role_id)
        if role is None:
            return TaskResult(
                success=False,
                error_message=f"Role '{role_id}' not found or has no executor=coding_agent",
            )

        # Resolve server_id before loading backend so session key is stable.
        server_id = config.get("server_id") or role.get("server_id")

        # Load the coding agent backend (also initialises self._registry)
        backend = self._get_backend(role, config)
        if backend is None:
            return TaskResult(
                success=False,
                error_message=f"Could not load coding agent backend for role '{role_id}'",
            )

        # Health check — if unreachable, attempt auto-start then re-check.
        # Only escalate to waiting_for_input if auto-start fails.
        try:
            await backend.health()
        except Exception:
            self._log(f"Task {task.id}: backend unhealthy, attempting auto-start (server_id={server_id})")
            backend = await self._auto_start_backend(role, config, server_id)
            if backend is None:
                hint = (
                    f"agent(action='start', agent_id='{server_id}')"
                    if server_id
                    else "agent(action='list') to see available servers, then agent(action='start', agent_id=...)"
                )
                return TaskResult(
                    success=False,
                    waiting_for_input=(
                        f"Coding agent backend not reachable and auto-start failed "
                        f"(server_id={server_id!r}). "
                        f"Start it manually with: {hint}"
                    ),
                )

        # Session ownership lives in BackendRegistry (coding-agent-mcp-tool).
        # MoJo never stores session IDs in task.config — the registry resumes
        # the right session automatically based on role_id + server_id.
        try:
            agent_session_id = await self._registry.get_or_create_session(
                role_id=role_id, server_id=server_id
            )
        except Exception as e:
            return TaskResult(
                success=False, error_message=f"Failed to get/create agent session: {e}"
            )

        self._log(f"Task {task.id}: using agent session {agent_session_id}")

        # Permission resume — state lives in SessionStore, not TaskConfig.
        reply = config.pop("reply_to_question", None)
        pending_perm = self._registry.pop_pending_permission(role_id, server_id)

        if pending_perm and reply is not None:
            perm_id = pending_perm.get("requestID") or pending_perm.get("id")
            response = self._map_reply_to_permission_response(reply)
            directory = pending_perm.get("directory", "")
            self._log(
                f"Responding to permission {perm_id} with '{response}' "
                f"(user said: '{reply}', directory: '{directory}')"
            )
            try:
                await backend.respond_to_permission(
                    agent_session_id, perm_id, response, directory=directory
                )
            except Exception as e:
                self._log(f"respond_to_permission failed: {e}", "warning")
                # Continue anyway — agent may have timed out the permission

        # Build resource / LLM config
        from app.scheduler.resource_pool import ResourceTier

        tier_pref_raw = config.get("tier_preference", task.resources.tier_preference)
        if isinstance(tier_pref_raw, str):
            tier_pref_raw = [tier_pref_raw]
        tier_preference = (
            [ResourceTier(t) for t in tier_pref_raw]
            if tier_pref_raw
            else [ResourceTier.FREE, ResourceTier.FREE_API]
        )

        role_model_preference = role.get("model_preference")
        preferred_resource_id = role.get("preferred_resource_id")
        max_iterations = config.get("max_iterations", task.resources.max_iterations)
        max_duration = config.get("max_duration_seconds", task.resources.max_duration_seconds or 600)

        # Build system prompt: role persona + coding agent context
        system_prompt = self._build_system_prompt(role, backend, agent_session_id)

        # Build initial messages (or resume existing LLM session)
        resume_from = config.get("resume_from_task_id")
        messages: list[dict]

        if resume_from:
            messages = self._load_resume_messages(resume_from, system_prompt)
            if messages is None:
                messages = self._initial_messages(system_prompt, goal, config, agent_session_id)
            else:
                # Inject context about the permission resume
                if pending_perm_id:
                    messages.append({
                        "role": "user",
                        "content": (
                            f"The permission request was resolved (user said: '{reply}' → '{response}'). "
                            "The agent session is still active — call `agent_send_message` to "
                            "continue toward the goal (the session remembers all previous work)."
                        ),
                    })
                elif reply:
                    messages.append({"role": "user", "content": f"User reply: {reply}"})
        else:
            messages = self._initial_messages(system_prompt, goal, config, agent_session_id)

        # Create session record
        session = TaskSession(
            task_id=task.id,
            status="running",
            messages=[],
            started_at=datetime.now().isoformat(),
            metadata={"goal": goal, "agent_session_id": agent_session_id},
        )
        self._session_storage.save_session(session)
        for msg in messages:
            self._record(task.id, msg.get("role", "unknown"), msg.get("content", "") or "", 0)

        # ------------------------------------------------------------------ #
        #  Main LLM loop                                                       #
        # ------------------------------------------------------------------ #

        start_time = time.time()
        final_answer: str | None = None

        for iteration in range(1, max_iterations + 1):
            if time.time() - start_time >= max_duration:
                self._log(f"Task {task.id}: time budget exhausted at iteration {iteration}")
                break

            resource = None
            if preferred_resource_id:
                resource = self._rm.acquire_by_id(preferred_resource_id)
                if resource is None:
                    self._log(
                        f"Preferred resource '{preferred_resource_id}' unavailable, "
                        "falling back to tier selection"
                    )
            if resource is None:
                resource = self._rm.acquire(tier_preference=tier_preference)
            if resource is None:
                self._log(f"No resource available, retrying in 30s (iteration {iteration})")
                await asyncio.sleep(30)
                resource = self._rm.acquire_by_id(preferred_resource_id) if preferred_resource_id else None
                if resource is None:
                    resource = self._rm.acquire(tier_preference=tier_preference)
                if resource is None:
                    self._log("Still no resource, aborting")
                    break

            try:
                response_data = await self._call_llm(
                    resource, messages, tools=_CODING_AGENT_TOOLS, model_override=role_model_preference
                )
                self._rm.record_usage(resource.id, success=True)
            except Exception as e:
                self._rm.record_usage(resource.id, success=False)
                self._log(f"LLM call failed at iteration {iteration}: {e}", "error")
                continue

            message = response_data["choices"][0]["message"]
            response_text = message.get("content", "") or message.get("reasoning_content", "") or ""
            tool_calls = message.get("tool_calls")

            if tool_calls:
                messages.append(message)
                self._record(task.id, "assistant", response_text, iteration)

                tool_results = await self._execute_tool_calls(
                    tool_calls, backend, agent_session_id, task
                )

                for tc, result_content in zip(tool_calls, tool_results):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_content,
                    })
                    self._record(
                        task.id, "tool", result_content, iteration,
                        tool_call_id=tc["id"],
                        tool_name=tc["function"]["name"],
                    )

                # Check if we paused for user input or a permission request
                if self._waiting_for_input_question or self._pending_permission:
                    break

                if iteration >= max_iterations - 1:
                    remaining = max_iterations - iteration
                    messages.append({
                        "role": "user",
                        "content": NEAR_LIMIT_PROMPT.format(
                            current=iteration, max=max_iterations, remaining=remaining
                        ),
                    })
                continue

            # Text response — check for final answer
            messages.append({"role": "assistant", "content": response_text})
            self._record(task.id, "assistant", response_text, iteration)

            final_answer = self._parse_final_answer(response_text)
            if final_answer:
                self._log(f"Task {task.id}: got final answer at iteration {iteration}")
                self._session_storage.update_status(task.id, "completed", final_answer=final_answer)
                break

            if iteration >= max_iterations - 1:
                remaining = max_iterations - iteration
                messages.append({
                    "role": "user",
                    "content": NEAR_LIMIT_PROMPT.format(
                        current=iteration, max=max_iterations, remaining=remaining
                    ),
                })
            else:
                messages.append({"role": "user", "content": CONTINUE_PROMPT})
                self._record(task.id, "user", CONTINUE_PROMPT, iteration)

        total_elapsed = round(time.time() - start_time, 1)
        session_file = str(self._session_storage._path(task.id))

        # Paused for HITL question from Popo itself
        if self._waiting_for_input_question:
            self._session_storage.update_status(task.id, "waiting_for_input")
            return TaskResult(
                success=False,
                waiting_for_input=self._waiting_for_input_question,
                output_file=session_file,
                metrics={"duration_seconds": total_elapsed, "session_file": session_file},
            )

        # Paused for agent permission — store state in SessionStore (not TaskConfig).
        # On resume, pop_pending_permission retrieves it automatically.
        if self._pending_permission:
            perm = self._pending_permission
            self._registry.set_pending_permission(role_id, server_id, perm)
            task.config["resume_from_task_id"] = task.id
            self._session_storage.update_status(task.id, "waiting_for_input")
            title = perm.get("title") or perm.get("type") or "permission required"
            return TaskResult(
                success=False,
                waiting_for_input=f"Agent needs permission: {title}",
                output_file=session_file,
                metrics={"duration_seconds": total_elapsed, "session_file": session_file},
            )

        success = final_answer is not None
        current = self._session_storage.load_session(task.id)
        if current and current.status == "running":
            self._session_storage.update_status(
                task.id,
                "completed" if success else "failed",
                final_answer=final_answer,
                error_message=None if success else "Agent did not produce a final answer",
            )

        return TaskResult(
            success=success,
            output_file=session_file,
            metrics={"duration_seconds": total_elapsed, "session_file": session_file},
            error_message=None if success else "Agent did not produce a final answer",
        )

    # ------------------------------------------------------------------ #
    #  Tool execution                                                      #
    # ------------------------------------------------------------------ #

    async def _execute_tool_calls(
        self,
        tool_calls: list[dict],
        backend: Any,
        agent_session_id: str,
        task: Task,
    ) -> list[str]:
        results = []
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                fn_args = {}

            try:
                result = await self._execute_single_tool(
                    fn_name, fn_args, backend, agent_session_id
                )
                results.append(json.dumps(result, default=str))
            except Exception as e:
                self._log(f"Tool {fn_name} failed: {e}", "error")
                results.append(json.dumps({"error": str(e)}))
        return results

    async def _execute_single_tool(
        self,
        name: str,
        args: dict,
        backend: Any,
        agent_session_id: str,
    ) -> Any:
        if name == "ask_user":
            self._waiting_for_input_question = args.get("question", "")
            return {"success": True, "message": f"Question submitted: {self._waiting_for_input_question}"}

        if name == "agent_get_messages":
            try:
                msgs = await backend.get_messages(agent_session_id)
                return {"messages": msgs, "count": len(msgs)}
            except Exception as e:
                return {"error": f"get_messages failed: {e}"}

        if name == "agent_send_message":
            instruction = args.get("instruction", "")
            return await self._send_with_permission_watch(
                backend, agent_session_id, instruction
            )

        return {"error": f"Unknown tool: {name}"}

    async def _send_with_permission_watch(
        self, backend: Any, session_id: str, content: str
    ) -> dict:
        """
        Fire send_message as a background task and poll GET /permission in parallel.

        Proven behaviour (see tests/test_hitl_capability_plan.py, CAP-3-1..4-2):
          - OpenCode holds the HTTP connection open while waiting for permission
          - GET /permission polling reliably detects pending permissions
          - SSE (permission.asked) is unreliable — polling is the primary mechanism
          - After cancel + respond_to_permission, the session stays alive and
            accepts new messages (full suspend/resume works)

        Returns:
          {"status": "completed",          "result": <assistant text>}
          {"status": "permission_required", "permission_id": ..., "permission_directory": ...}
          {"status": "timeout",             "result": "(timed out)"}
        """
        send_result: dict | None = None
        send_error: Exception | None = None

        async def _send():
            nonlocal send_result, send_error
            try:
                send_result = await backend.send_message(session_id, content)
            except Exception as e:
                send_error = e
                self._log(f"send_message raised: {e}", "warning")

        send_task = asyncio.create_task(_send())

        # Poll for permission or wait for send_task to complete naturally
        deadline = asyncio.get_event_loop().time() + 280.0
        while asyncio.get_event_loop().time() < deadline:
            if send_task.done():
                break

            await asyncio.sleep(3)

            if send_task.done():
                break

            try:
                perms = await backend.list_permissions(session_id)
                if perms:
                    perm = perms[0]
                    perm_id = perm.get("requestID") or perm.get("id")
                    title = perm.get("title") or perm.get("permission") or "unknown"
                    self._log(f"Permission detected: {title} ({perm_id})")
                    self._pending_permission = perm
                    send_task.cancel()
                    with suppress(Exception, asyncio.CancelledError):
                        await send_task
                    return {
                        "status": "permission_required",
                        "message": f"Agent needs permission: {title}",
                        "permission_id": perm_id,
                        "permission_directory": perm.get("directory", ""),
                    }
            except Exception as e:
                self._log(f"list_permissions error: {e}", "warning")

        # Timed out without completing
        if not send_task.done():
            send_task.cancel()
            with suppress(Exception, asyncio.CancelledError):
                await send_task
            self._log("send_message timed out after 280s", "warning")
            return {"status": "timeout", "result": "(timed out — no response from coding agent)"}

        if send_error is not None:
            raise send_error

        # Extract assistant text from the response
        parts = (send_result or {}).get("parts", [])
        text = "\n".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
        return {"status": "completed", "result": text or "(no text response)"}

    # ------------------------------------------------------------------ #
    #  LLM call                                                            #
    # ------------------------------------------------------------------ #

    async def _call_llm(
        self,
        resource: Any,
        messages: list[dict],
        tools: list[dict] | None = None,
        model_override: str | None = None,
    ) -> dict:
        from app.llm.unified_client import UnifiedLLMClient

        selected_model = model_override or resource.model
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
        if not data.get("choices"):
            raise ValueError("LLM returned no choices")
        return data

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _load_role(self, role_id: str | None) -> dict | None:
        if not role_id:
            return None
        try:
            from app.roles.role_manager import RoleManager
            role = RoleManager().get(role_id)
            if role and role.get("executor") == "coding_agent":
                return role
            return None
        except Exception as e:
            self._log(f"Failed to load role '{role_id}': {e}", "warning")
            return None

    async def _auto_start_backend(
        self, role: dict, config: dict, server_id: str | None
    ) -> Any | None:
        """
        Attempt to auto-start the backend for *server_id*, then poll until
        healthy. Returns a healthy backend or None on failure.

        Backend-type routing:
        - opencode  → OpenCodeManager.start_project (HTTP server must be launched)
        - claude_code → no-op (binary always present; health() validates working_dir)
        - unknown   → log warning, skip
        """
        if not server_id:
            self._log("No server_id — cannot auto-start backend", "warning")
            return None

        backend = self._get_backend(role, config)
        backend_type = getattr(backend, "backend_type", None) if backend else None

        if backend_type == "claude_code":
            # Claude Code is a local binary — no server to start.
            # health() already validates the binary and working_dir.
            self._log(f"claude_code backend ({server_id}): no auto-start needed")
            return backend

        if backend_type == "opencode":
            try:
                from app.mcp.opencode.manager import OpenCodeManager
                manager = OpenCodeManager()
                result = await manager.start_project(server_id)
                status = result.get("status", "")
                self._log(f"Auto-start result for {server_id}: {status}")
                if status not in ("success", "already_running", "running"):
                    self._log(f"Auto-start did not succeed: {result}", "warning")
                    return None
            except Exception as e:
                self._log(f"Auto-start exception for {server_id}: {e}", "warning")
                return None

            # Poll until healthy (up to 90 s, 6 s intervals)
            deadline = asyncio.get_event_loop().time() + 90
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(6)
                backend = self._get_backend(role, config)
                if backend is not None:
                    try:
                        await backend.health()
                        self._log(f"Backend {server_id} is healthy after auto-start")
                        return backend
                    except Exception:
                        pass
                self._log("Waiting for backend to become healthy…")

            self._log(f"Backend {server_id} still unhealthy after 90 s", "warning")
            return None

        self._log(
            f"Unknown backend_type {backend_type!r} for {server_id} — skipping auto-start",
            "warning",
        )
        return None

    def _get_registry(self) -> Any:
        """Return the cached BackendRegistry, loading config on first call."""
        from coding_agent_mcp.backends import BackendRegistry
        from coding_agent_mcp.config.loader import load_config

        if self._registry is None:
            cfg = load_config()
            self._registry = BackendRegistry()
            self._registry.reload(cfg.servers, cfg.default_server)
        return self._registry

    def _get_backend(self, role: dict, config: dict) -> Any | None:
        server_id = config.get("server_id") or role.get("server_id")
        try:
            return self._get_registry().get(server_id)  # server_id=None → default
        except Exception as e:
            self._log(f"Failed to load coding agent backend (server_id={server_id}): {e}", "warning")
            return None

    def _build_system_prompt(self, role: dict, backend: Any, session_id: str) -> str:
        persona = role.get("system_prompt", "You are a coding assistant.")
        backend_type = getattr(backend, "backend_type", "coding agent")
        context = (
            f"\n\n---\n\n"
            f"## Coding Agent Context\n\n"
            f"You are driving an external coding agent ({backend_type}) via tool calls.\n"
            f"Agent session ID: `{session_id}`\n\n"
            f"**How to work:**\n"
            f"1. Break the goal into discrete steps.\n"
            f"2. Send each step to the agent via `agent_send_message`.\n"
            f"3. Read results and plan the next step.\n"
            f"4. If the agent asks for a permission, the request will be paused and routed to the user.\n"
            f"5. When the task is complete, summarise what was done in a `<FINAL_ANSWER>`.\n\n"
            f"Call `agent_get_messages()` first if you are resuming a previous session."
        )
        return persona + context

    def _initial_messages(
        self, system_prompt: str, goal: str, config: dict, session_id: str
    ) -> list[dict]:
        user_content = f"Goal: {goal}"
        context = config.get("context")
        if context:
            user_content += f"\n\nContext:\n{json.dumps(context, indent=2, default=str)}"
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def _load_resume_messages(
        self, task_id: str, system_prompt: str
    ) -> list[dict] | None:
        session = self._session_storage.load_session(task_id)
        if session is None:
            return None
        messages: list[dict] = []
        for msg in session.messages:
            entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            messages.append(entry)
        return messages or None

    @staticmethod
    def _map_reply_to_permission_response(reply: str) -> str:
        """Map a user's free-text reply to one of: once | always | reject."""
        r = reply.strip().lower()
        if r in ("always", "always approve", "approve always"):
            return "always"
        if r in ("reject", "no", "deny", "block"):
            return "reject"
        return "once"  # default: approve once

    @staticmethod
    def _parse_final_answer(text: str) -> str | None:
        open_tag = "<FINAL_ANSWER>"
        close_tag = "</FINAL_ANSWER>"
        start = text.find(open_tag)
        if start == -1:
            return None
        start += len(open_tag)
        end = text.find(close_tag, start)
        return (text[start:] if end == -1 else text[start:end]).strip() or None

    def _record(
        self, task_id: str, role: str, content: str, iteration: int, **kwargs: Any
    ) -> None:
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
