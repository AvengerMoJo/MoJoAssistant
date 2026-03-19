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

# Popo tool definitions for the LLM
_OPENCODE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "opencode_send_message",
            "description": (
                "Send an instruction to the OpenCode coding agent and wait for it to respond. "
                "OpenCode has shell access, can read/write files, run tests, and use tools. "
                "The response will include what OpenCode did and any output it produced."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "Clear instruction for OpenCode to execute",
                    }
                },
                "required": ["instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opencode_get_messages",
            "description": (
                "Get the full conversation history of the current OpenCode session, "
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
            goal (str): What Popo should accomplish.
            role_id (str): Which role to load (must have executor="coding_agent").
            opencode_session_id (str, optional): Existing OpenCode session to resume.
            opencode_pending_permission_id (str, optional): Permission ID awaiting response.
            resume_from_task_id (str, optional): Resume a previous LLM session.
            reply_to_question (str, optional): User reply injected after WAITING_FOR_INPUT.
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

        # Load the OpenCode backend
        backend = self._get_backend(role, config)
        if backend is None:
            return TaskResult(
                success=False,
                error_message=f"Could not load coding agent backend for role '{role_id}'",
            )

        # Health check
        try:
            await backend.health()
        except Exception as e:
            return TaskResult(success=False, error_message=f"Coding agent not reachable: {e}")

        # Get or create an OpenCode session
        opencode_session_id = config.get("opencode_session_id")
        if not opencode_session_id:
            try:
                session_data = await backend.create_session()
                opencode_session_id = session_data.get("id") or session_data.get("sessionID")
                if not opencode_session_id:
                    return TaskResult(
                        success=False,
                        error_message=f"OpenCode session create returned no ID: {session_data}",
                    )
                # Persist for resume
                task.config["opencode_session_id"] = opencode_session_id
            except Exception as e:
                return TaskResult(
                    success=False, error_message=f"Failed to create OpenCode session: {e}"
                )

        self._log(f"Task {task.id}: using OpenCode session {opencode_session_id}")

        # If resuming after a permission was granted by the user
        pending_perm_id = config.pop("opencode_pending_permission_id", None)
        reply = config.pop("reply_to_question", None)

        if pending_perm_id and reply is not None:
            response = self._map_reply_to_permission_response(reply)
            self._log(
                f"Responding to permission {pending_perm_id} with '{response}' "
                f"(user said: '{reply}')"
            )
            try:
                await backend.respond_to_permission(opencode_session_id, pending_perm_id, response)
            except Exception as e:
                self._log(f"respond_to_permission failed: {e}", "warning")
                # Continue anyway — OpenCode may have timed out the permission

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
        max_iterations = config.get("max_iterations", task.resources.max_iterations)
        max_duration = config.get("max_duration_seconds", task.resources.max_duration_seconds or 600)

        # Build system prompt: role persona + coding agent context
        system_prompt = self._build_system_prompt(role, backend, opencode_session_id)

        # Build initial messages (or resume existing LLM session)
        resume_from = config.get("resume_from_task_id")
        messages: list[dict]

        if resume_from:
            messages = self._load_resume_messages(resume_from, system_prompt)
            if messages is None:
                messages = self._initial_messages(system_prompt, goal, config, opencode_session_id)
            else:
                # Inject context about the permission resume
                if pending_perm_id:
                    messages.append({
                        "role": "user",
                        "content": (
                            f"The OpenCode permission request has been resolved (response: {response}). "
                            "Call `opencode_get_messages()` to check the current session state, "
                            "then continue toward the goal."
                        ),
                    })
                elif reply:
                    messages.append({"role": "user", "content": f"User reply: {reply}"})
        else:
            messages = self._initial_messages(system_prompt, goal, config, opencode_session_id)

        # Create session record
        session = TaskSession(
            task_id=task.id,
            status="running",
            messages=[],
            started_at=datetime.now().isoformat(),
            metadata={"goal": goal, "opencode_session_id": opencode_session_id},
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

            resource = self._rm.acquire(tier_preference=tier_preference)
            if resource is None:
                self._log(f"No resource available, retrying in 30s (iteration {iteration})")
                await asyncio.sleep(30)
                resource = self._rm.acquire(tier_preference=tier_preference)
                if resource is None:
                    self._log("Still no resource, aborting")
                    break

            try:
                response_data = await self._call_llm(
                    resource, messages, tools=_OPENCODE_TOOLS, model_override=role_model_preference
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
                    tool_calls, backend, opencode_session_id, task
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

        # Paused for OpenCode permission — store permission_id for resume
        if self._pending_permission:
            perm = self._pending_permission
            task.config["opencode_pending_permission_id"] = perm.get("id")
            task.config["resume_from_task_id"] = task.id
            self._session_storage.update_status(task.id, "waiting_for_input")
            title = perm.get("title") or perm.get("type") or "permission required"
            return TaskResult(
                success=False,
                waiting_for_input=f"OpenCode needs permission: {title}",
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
        opencode_session_id: str,
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
                    fn_name, fn_args, backend, opencode_session_id
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
        opencode_session_id: str,
    ) -> Any:
        if name == "ask_user":
            self._waiting_for_input_question = args.get("question", "")
            return {"success": True, "message": f"Question submitted: {self._waiting_for_input_question}"}

        if name == "opencode_get_messages":
            try:
                msgs = await backend.get_messages(opencode_session_id)
                return {"messages": msgs, "count": len(msgs)}
            except Exception as e:
                return {"error": f"get_messages failed: {e}"}

        if name == "opencode_send_message":
            instruction = args.get("instruction", "")
            return await self._send_with_permission_watch(
                backend, opencode_session_id, instruction
            )

        return {"error": f"Unknown tool: {name}"}

    async def _send_with_permission_watch(
        self, backend: Any, session_id: str, content: str
    ) -> dict:
        """
        Race send_message against the first incoming permission event.

        - Normal case: OpenCode responds → return result to Popo
        - Permission case: OpenCode blocks on permission → set self._pending_permission,
          cancel send_message, signal the loop to pause
        """
        send_task = asyncio.create_task(backend.send_message(session_id, content))
        perm_task = asyncio.create_task(self._first_permission(backend, session_id))

        done, pending = await asyncio.wait(
            {send_task, perm_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for t in pending:
            t.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await t

        # Permission arrived first
        if perm_task in done and not perm_task.cancelled():
            exc = perm_task.exception()
            if exc is None:
                perm = perm_task.result()
                self._pending_permission = perm
                title = perm.get("title") or perm.get("type") or "unknown"
                return {
                    "status": "permission_required",
                    "message": f"OpenCode paused — permission required: {title}",
                    "permission_id": perm.get("id"),
                }

        # Send completed (normal path or send_task had an error)
        if send_task in done and not send_task.cancelled():
            exc = send_task.exception()
            if exc is not None:
                raise exc
            return {"status": "completed", "result": send_task.result()}

        # Edge case: both cancelled or both errored
        raise RuntimeError("opencode_send_message: unexpected completion state")

    async def _first_permission(self, backend: Any, session_id: str) -> dict:
        """Return the first permission event from the SSE stream."""
        async for perm in backend.subscribe_permissions(session_id):
            return perm
        raise RuntimeError("Permission stream ended without a permission event")

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

    def _get_backend(self, role: dict, config: dict) -> Any | None:
        server_id = config.get("server_id") or role.get("server_id")
        try:
            from coding_agent_mcp.backends import BackendRegistry
            from coding_agent_mcp.config.loader import load_config

            cfg = load_config()
            registry = BackendRegistry()
            registry.reload(cfg.servers, cfg.default_server)
            return registry.get(server_id)  # server_id=None → default
        except Exception as e:
            self._log(f"Failed to load coding agent backend (server_id={server_id}): {e}", "warning")
            return None

    def _build_system_prompt(self, role: dict, backend: Any, session_id: str) -> str:
        persona = role.get("system_prompt", "You are a coding assistant.")
        context = (
            f"\n\n---\n\n"
            f"## Coding Agent Context\n\n"
            f"You are driving an external coding agent (OpenCode) via tool calls.\n"
            f"OpenCode session ID: `{session_id}`\n\n"
            f"**How to work:**\n"
            f"1. Break the goal into discrete steps.\n"
            f"2. Send each step to OpenCode via `opencode_send_message`.\n"
            f"3. Read results and plan the next step.\n"
            f"4. If OpenCode asks for a permission, the request will be paused and routed to the user.\n"
            f"5. When the task is complete, summarise what was done in a `<FINAL_ANSWER>`.\n\n"
            f"Call `opencode_get_messages()` first if you are resuming a previous session."
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
