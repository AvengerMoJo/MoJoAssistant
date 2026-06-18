"""
OpenCode coding session handler.

Lifecycle:
  PENDING        → create session (if needed) → start send_message + SSE watcher
  WAITING_FOR_INPUT → user replied → respond_to_permission → re-enter send_message
  send_message returns → COMPLETED, send push notification
  send_message times out → chain "continue" message, stay RUNNING
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult, TaskStatus

logger = logging.getLogger(__name__)


class OpenCodeSessionHandler(TaskHandler):

    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        cfg = task.config or {}
        mode = cfg.get("_mode", "run")

        if mode == "resume":
            return await self._resume(task, ctx)
        if mode == "resume_question":
            return await self._resume_question(task, ctx)
        return await self._run(task, ctx)

    # ------------------------------------------------------------------
    # Run mode — create/rejoin session and send message
    # ------------------------------------------------------------------

    async def _run(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        backend = self._get_backend(task)
        cfg = task.config

        # Create or rejoin session
        session_id = cfg.get("session_id") or ""
        if not session_id:
            session = await backend.create_session()
            session_id = session.get("id") or session.get("sessionID")
            if not session_id:
                return TaskResult(
                    success=False,
                    error_message=f"OpenCode create_session returned no ID: {session}",
                )
            cfg["session_id"] = session_id
            ctx.queue.update(task)

        prompt = cfg.get("prompt", "")

        # Run send_message and SSE permission watcher concurrently
        task_send = asyncio.create_task(
            backend.send_message(session_id, prompt)
        )
        task_sse = asyncio.create_task(
            self._sse_first_permission(backend, session_id)
        )

        done, _ = await asyncio.wait(
            [task_send, task_sse],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Case 1: SSE finished first — permission or question event
        if task_sse in done:
            sse_exc = task_sse.exception()
            if sse_exc is None:
                event = task_sse.result()
                if event is not None:
                    task_send.cancel()
                    try:
                        await task_send
                    except (asyncio.CancelledError, Exception):
                        pass
                    if event.get("type") == "question.asked":
                        return await self._handle_question_hitl(task, ctx, event)
                    return await self._handle_permission(task, ctx, event)
            else:
                logger.debug("SSE watcher exited with exception: %s", sse_exc)
            # SSE ended without a permission (None result or connection error).
            # send_message is still running — wait for it before proceeding.
            if task_send not in done:
                done2, _ = await asyncio.wait([task_send])
                done = done | done2

        # Case 2: send_message has a result
        if task_send in done:
            task_sse.cancel()
            exc = task_send.exception()
            if exc is not None:
                exc_str = str(exc)
                exc_type = type(exc).__name__
                if (not exc_str or "timed out" in exc_str.lower()
                        or "ReadTimeout" in exc_type or "Timeout" in exc_type
                        or "RemoteProtocol" in exc_type or "ConnectionReset" in exc_type):
                    return await self._chain_continue(task, ctx, backend, session_id)
                return TaskResult(success=False, error_message=exc_str or exc_type)
            result = task_send.result()
            return await self._complete(task, ctx, result)

        # Should not be reachable after the waits above
        task_send.cancel()
        task_sse.cancel()
        return TaskResult(success=False, error_message="unexpected wait state")

    # ------------------------------------------------------------------
    # Resume mode — user replied to a permission HITL
    # ------------------------------------------------------------------

    async def _resume(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        """
        Called after the user replies to a permission HITL.

        Expected task.config keys set before resume dispatch:
          session_id, perm_id, perm_directory, _user_reply
        """
        backend = self._get_backend(task)
        cfg = task.config

        perm_id = cfg.get("perm_id", "")
        perm_dir = cfg.get("perm_directory", "")
        user_reply = cfg.get("_user_reply") or cfg.get("reply_to_question", "once")

        # Translate user reply to OpenCode permission response
        reply = _map_user_reply_to_permission(user_reply)

        try:
            await backend.respond_to_permission(
                cfg["session_id"], perm_id, reply, directory=perm_dir
            )
        except Exception as e:
            return TaskResult(success=False, error_message=f"respond_to_permission failed: {e}")

        # Clear resume state, re-enter run loop with "continue" prompt
        cfg.pop("_mode", None)
        cfg.pop("perm_id", None)
        cfg.pop("perm_directory", None)
        cfg.pop("_user_reply", None)
        cfg.pop("reply_to_question", None)
        cfg.pop("_poll_count", None)
        cfg["prompt"] = "continue"
        ctx.queue.update(task)

        return await self._run(task, ctx)

    # ------------------------------------------------------------------
    # Permission HITL
    # ------------------------------------------------------------------

    async def _handle_permission(
        self, task: Task, ctx: ExecutorContext, perm: Dict[str, Any]
    ) -> TaskResult:
        """
        Save permission state, set task to WAITING_FOR_INPUT, push Discord HITL.
        """
        perm_id = perm.get("requestID") or perm.get("id", "")
        perm_dir = perm.get("directory", "")
        title = perm.get("title", "")
        perm_type = perm.get("type", "action")

        task.config["_mode"] = "resume"
        task.config["perm_id"] = perm_id
        task.config["perm_directory"] = perm_dir
        task.status = TaskStatus.WAITING_FOR_INPUT
        task.pending_question = (
            f"OpenCode wants to {perm_type}: {title}\n"
            f"Reply: once / always / reject"
        )
        ctx.queue.update(task)

        # Push HITL notification
        await _push_hitl_notification(ctx, task)

        # Return waiting_for_input so the scheduler sets WAITING_FOR_INPUT
        # and exits early at core.py:472 — never reaches mark_completed().
        return TaskResult(
            success=True,
            waiting_for_input=task.pending_question,
            waiting_for_input_choices=["once", "always", "reject"],
        )

    # ------------------------------------------------------------------
    # Question HITL (OpenCode Question API — arbitrary user questions)
    # ------------------------------------------------------------------

    async def _poll_questions(
        self, backend, session_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Poll GET /question for any pending questions in this session.
        Returns the first Question.Request object, or None.
        """
        try:
            for q in await backend.list_questions(session_id):
                return q
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Completion and chaining
    # ------------------------------------------------------------------

    async def _complete(
        self, task: Task, ctx: ExecutorContext, result: Dict[str, Any]
    ) -> TaskResult:
        summary = _extract_text(result)
        await _push_completion_notification(ctx, task, summary)
        return TaskResult(success=True, metrics={"result": summary, "raw": result})

    async def _chain_continue(
        self, task: Task, ctx: ExecutorContext, backend, session_id: str
    ) -> TaskResult:
        """
        send_message timed out — OpenCode is still running on its side.
        Poll every 5 minutes for completion instead of sending a new message
        (which would interrupt the running agent).
        """
        _POLL_INTERVAL = 300  # 5 minutes
        _MAX_POLLS = 36       # 3 hours total ceiling

        polls = task.config.get("_poll_count", 0)
        if polls >= _MAX_POLLS:
            return TaskResult(
                success=False,
                error_message=f"OpenCode session {session_id} still running after 3 hours — giving up",
            )

        # Check for pending question first
        q = await self._poll_questions(backend, session_id)
        if q:
            task.config.pop("_poll_count", None)
            return await self._handle_question_hitl(task, ctx, q)

        # Check if the session has a completed response we haven't seen yet
        try:
            messages = await backend.get_messages(session_id)
            if messages:
                last = messages[-1]
                if last.get("role") == "assistant":
                    task.config.pop("_poll_count", None)
                    ctx.queue.update(task)
                    return await self._complete(task, ctx, last)
        except Exception as e:
            logger.debug("_chain_continue: get_messages failed: %s", e)

        # Still running — wait 5 min then check again
        task.config["_poll_count"] = polls + 1
        task.config["session_id"] = session_id
        ctx.queue.update(task)
        logger.info(
            "OpenCodeSessionHandler: agent still running, poll %d/%d for task %s — sleeping %ds",
            polls + 1, _MAX_POLLS, task.id, _POLL_INTERVAL,
        )
        await asyncio.sleep(_POLL_INTERVAL)
        return await self._chain_continue(task, ctx, backend, session_id)

    async def _handle_question_hitl(
        self, task: Task, ctx: ExecutorContext, q: Dict[str, Any]
    ) -> TaskResult:
        """
        Surface a Question API HITL to the owner.

        q shape:
          {"id": "que...", "sessionID": "...", "questions": [
            {"question": "...", "header": "...", "options": [...], "custom": bool}
          ]}
        """
        qid = q.get("id", "")
        first_q = (q.get("questions") or [{}])[0]
        question_text = first_q.get("question", "Question from coding agent")
        options = first_q.get("options") or []
        custom = first_q.get("custom", True)

        task.config["_mode"] = "resume_question"
        task.config["question_id"] = qid
        task.status = TaskStatus.WAITING_FOR_INPUT
        task.pending_question = question_text
        if options:
            task.config["pending_options"] = options
        task.config["question_custom"] = custom
        ctx.queue.update(task)

        await _push_hitl_notification(ctx, task)
        return TaskResult(
            success=True,
            waiting_for_input=question_text,
            waiting_for_input_choices=options if options else None,
        )

    # ------------------------------------------------------------------
    # Resume question (Question API reply)
    # ------------------------------------------------------------------

    async def _resume_question(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        """Called after the user replies to a Question API HITL."""
        backend = self._get_backend(task)
        cfg = task.config
        qid = cfg.get("question_id", "")
        user_reply = cfg.get("_user_reply") or cfg.get("ext_agent_reply") or cfg.get("reply_to_question", "")

        if not user_reply:
            return TaskResult(success=False, error_message="no reply found in task config")

        try:
            await backend.reply_to_question(qid, user_reply)
        except Exception as e:
            return TaskResult(success=False, error_message=f"question reply failed: {e}")

        # Clear resume state, re-enter run loop
        cfg.pop("_mode", None)
        cfg.pop("question_id", None)
        cfg.pop("_user_reply", None)
        cfg.pop("ext_agent_reply", None)
        cfg.pop("reply_to_question", None)
        cfg["prompt"] = "continue"
        ctx.queue.update(task)
        return await self._run(task, ctx)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_backend(self, task: Task):
        # Prefer sandbox_id (new path) → start sandbox, derive URL dynamically.
        # Fall back to server_id (legacy static config path).
        sandbox_id = (task.config.get("sandbox_id") or "").strip()
        if sandbox_id:
            from app.sandbox.manager import SandboxManager
            from coding_agent_mcp.backends.opencode import OpenCodeBackend
            mgr = SandboxManager()
            url = mgr.get_or_start(sandbox_id)
            entry = mgr.get(sandbox_id)
            if entry.agent_type == "claude_code":
                from coding_agent_mcp.backends.claude_code import ClaudeCodeBackend
                from coding_agent_mcp.config.models import ServerEntry
                return ClaudeCodeBackend.from_config(
                    ServerEntry(id=sandbox_id, backend_type="claude_code", working_dir=url)
                )
            return OpenCodeBackend(server_id=sandbox_id, base_url=url, password=entry.password)

        # Legacy: load from static coding_agent_servers.json
        from coding_agent_mcp.backends import BackendRegistry
        from coding_agent_mcp.config.loader import load_config
        cfg_obj = load_config()
        reg = BackendRegistry()
        reg.reload(cfg_obj.servers, cfg_obj.default_server)
        server_id = task.config.get("server_id") or ""
        return reg.get(server_id if server_id else None)

    async def _sse_first_permission(self, backend, session_id: str):
        """
        Subscribe to /session/{id}/event and return the first permission.asked event.
        Returns None if the stream ends without a permission.
        """
        try:
            async for perm in backend.subscribe_permissions(session_id):
                return perm
        except Exception as e:
            logger.debug("SSE permission watcher ended: %s", e)
        return None


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _extract_text(result: Dict[str, Any]) -> str:
    for part in result.get("parts", []):
        if part.get("type") == "text":
            return part.get("text", "")
    return str(result)


def _map_user_reply_to_permission(reply: str) -> str:
    r = reply.lower().strip()
    if r in ("always", "yes always"):
        return "always"
    if r in ("reject", "no", "deny"):
        return "reject"
    return "once"


async def _push_hitl_notification(ctx: ExecutorContext, task: Task) -> None:
    """Send a Discord HITL push for a WAITING_FOR_INPUT task."""
    try:
        from app.mcp.adapters.hitl.manager import HITLManager
        mgr = HITLManager.load_from_config()
        if ctx._scheduler:
            mgr.set_scheduler(ctx._scheduler)
        choices = task.config.get("pending_options") or ["once", "always", "reject"]
        await mgr.send_hitl(
            task_id=task.id,
            question=task.pending_question or "",
            choices=choices,
        )
    except Exception as e:
        logger.warning("HITL push failed for task %s: %s", task.id, e)


async def _push_completion_notification(
    ctx: ExecutorContext, task: Task, summary: str
) -> None:
    """Send a completion push notification."""
    try:
        from app.mcp.adapters.hitl.manager import HITLManager
        mgr = HITLManager.load_from_config()
        if ctx._scheduler:
            mgr.set_scheduler(ctx._scheduler)
        msg = f"Coding task complete [{task.id}]:\n{summary[:300]}"
        await mgr.send_notification(title="Coding Session Complete", body=msg)
    except Exception as e:
        logger.warning("Completion push failed for task %s: %s", task.id, e)
