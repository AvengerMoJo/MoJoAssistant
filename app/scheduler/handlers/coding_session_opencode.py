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
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult, TaskStatus

logger = logging.getLogger(__name__)


class TaskLogAdapter(logging.LoggerAdapter):
    """Logger adapter that prefixes every message with the task_id.

    Until we have per-task OpenCode instances (Phase 2), this gives every
    log line a task_id tag so the scheduler log file can be filtered by task.
    """
    def process(self, msg, kwargs):
        # LoggerAdapter stores the dict in self.extra; older code accessed
        # it as an attribute — both forms are common in stdlib examples.
        if isinstance(self.extra, dict):
            task_id = self.extra.get("task_id")
        else:
            task_id = getattr(self.extra, "task_id", None)
        if task_id:
            return f"[{task_id}] {msg}", kwargs
        return msg, kwargs


def _task_logger(task_id: str) -> logging.LoggerAdapter:
    return TaskLogAdapter(logger, {"task_id": task_id})


# Tasks hitting the scheduler's max_duration cap (default 1800s = 30 min) get
# killed mid-build with no warning. This helper logs a countdown so the dashboard
# shows the user their task is approaching the wall.
TASK_DURATION_CAP_S = 1800
TASK_DURATION_WARN_S = 300   # warn 5 min before cap


def _check_duration_warn(task: Task, log: logging.LoggerAdapter) -> None:
    started = task.started_at
    if not started:
        return
    # Normalize to aware UTC for comparison — some code paths set naive
    # datetimes, others set tz-aware.
    now = datetime.now(timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = (now - started).total_seconds()
    remaining = TASK_DURATION_CAP_S - elapsed
    if remaining < 0:
        log.warning("Task exceeded duration cap (%ds); will be killed by scheduler", TASK_DURATION_CAP_S)
    elif remaining < TASK_DURATION_WARN_S:
        log.warning(
            "Task approaching duration cap: %ds remaining (cap=%ds). "
            "Reply via reply_to_task to extend, or wait for completion.",
            int(remaining), TASK_DURATION_CAP_S,
        )


class OpenCodeSessionHandler(TaskHandler):

    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        cfg = task.config or {}
        mode = cfg.get("_mode", "run")
        log = _task_logger(task.id)

        log.info("execute start: mode=%s backend_type=%s working_dir=%r",
                 mode, cfg.get("backend_type"), cfg.get("working_dir"))

        if mode == "resume":
            return await self._resume(task, ctx)
        if mode == "resume_question":
            return await self._resume_question(task, ctx)
        return await self._run(task, ctx)

    # ------------------------------------------------------------------
    # Run mode — create/rejoin session and send message
    # ------------------------------------------------------------------

    async def _run(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        client = await self._get_client(task)
        cfg = task.config
        try:
            return await self._run_inner(task, ctx, client, cfg)
        finally:
            await self._cleanup(task, ctx)

    async def _run_inner(self, task: Task, ctx: ExecutorContext, client, cfg) -> "TaskResult":
        from app.scheduler.models import TaskResult, TaskStatus
        log = _task_logger(task.id)

        # Check duration cap (once at start so the user gets a warning early)
        _check_duration_warn(task, log)

        # Create or rejoin session
        session_id = cfg.get("session_id") or ""
        if not session_id:
            session = await client.create_session()
            session_id = session.get("id") or session.get("sessionID")
            if not session_id:
                return TaskResult(
                    success=False,
                    error_message=f"OpenCode create_session returned no ID: {session}",
                )
            cfg["session_id"] = session_id
            ctx._scheduler.queue.update(task)

        prompt = cfg.get("prompt", "")

        # Run send_message + two permission watchers concurrently:
        #   task_sse  — SSE event stream (fast, may miss newer OpenCode versions)
        #   task_poll — HTTP /permission polling (slower but reliable, 1s interval)
        # Whichever finds a permission first triggers HITL.
        task_send = asyncio.create_task(
            client.send_message(session_id, prompt)
        )
        task_sse = asyncio.create_task(
            self._sse_first_permission(client, session_id)
        )
        task_poll = asyncio.create_task(
            self._poll_first_hitl(client, session_id)
        )

        # Whichever finishes first wins; cancel the others
        done, pending = await asyncio.wait(
            [task_send, task_sse, task_poll],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()

        # Case 1: Poller won (OpenCode 1.17+ uses /permission and /question,
        # not the SSE event stream). Handler dispatches to permission or
        # question HITL based on the event type.
        if task_poll in done:
            poll_exc = task_poll.exception()
            if poll_exc is None:
                hitl = task_poll.result()
                if hitl is not None:
                    task_send.cancel()
                    try:
                        await task_send
                    except (asyncio.CancelledError, Exception):
                        pass
                    if hitl["type"] == "question":
                        return await self._handle_question_hitl(task, ctx, hitl["data"])
                    return await self._handle_permission(task, ctx, hitl["data"])
            else:
                logger.debug("HITL poller exited with exception: %s", poll_exc)

        # Case 2: SSE won (older OpenCode or polled event arrived first)
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

        # Case 3: send_message won — both watchers returned no permission
        # (or raised). Wait for it to finish if not already.
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
                    return await self._chain_continue(task, ctx, client, session_id)
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

    async def _resume(self, task: Task, ctx: ExecutorContext) -> "TaskResult":
        """
        Called after the user replies to a permission HITL.

        Expected task.config keys set before resume dispatch:
          session_id, perm_id, perm_directory, _user_reply
        """
        client = await self._get_client(task)
        try:
            return await self._resume_inner(task, ctx, client)
        finally:
            await self._cleanup(task, ctx)

    async def _resume_inner(self, task: Task, ctx: ExecutorContext, client) -> "TaskResult":
        cfg = task.config

        perm_id = cfg.get("perm_id", "")
        perm_dir = cfg.get("perm_directory", "")
        user_reply = cfg.get("_user_reply") or cfg.get("reply_to_question", "once")

        # Translate user reply to OpenCode permission response
        reply = _map_user_reply_to_permission(user_reply)

        try:
            await client.respond_to_permission(
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
        ctx._scheduler.queue.update(task)

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
        ctx._scheduler.queue.update(task)

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
            for q in await client.list_questions(session_id):
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

    async def _cleanup(self, task: Task, ctx: ExecutorContext) -> None:
        """Release resources owned by this task: CubeSandbox VM, per-task OpenCode, etc.

        Called in a finally block so cleanup happens on success, failure, timeout.
        Only resources marked as owned by THIS task are released — never stops
        a sandbox that was already running before the task started.
        """
        cfg = task.config or {}

        # CubeSandbox VM (only if we started it in this task)
        if cfg.get("_owned_cube"):
            cube = cfg.get("_cube_client")
            if cube:
                try:
                    cube.kill()
                    logger.info("Killed CubeSandbox VM for task %s", task.id)
                except Exception as e:
                    logger.warning("CubeSandbox cleanup failed for %s: %s", task.id, e)

        # Per-task OpenCode (Phase 2: OpenCodePerTaskBackend) — kill our instance
        ptb = cfg.get("_per_task_backend")
        if ptb:
            try:
                if ptb.kill(task.id):
                    logger.info("Killed per-task OpenCode for %s", task.id)
            except Exception as e:
                logger.warning("Per-task OpenCode cleanup failed for %s: %s", task.id, e)

        # Legacy: per-task sandbox (only if start_new=True created it via SandboxManager)
        owned_sandbox = cfg.get("_owned_sandbox")
        if owned_sandbox:
            try:
                from app.sandbox.manager import SandboxManager
                mgr = SandboxManager()
                mgr.stop(owned_sandbox)
                logger.info("Stopped per-task sandbox %s for task %s", owned_sandbox, task.id)
            except Exception as e:
                logger.warning("Sandbox cleanup failed for %s: %s", owned_sandbox, e)

        # Best-effort: close the OpenCode HTTP client
        client = cfg.get("_opencode_client")
        if client:
            try:
                await client.close()
            except Exception:
                pass

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
            messages = await client.get_messages(session_id)
            if messages:
                last = messages[-1]
                if last.get("role") == "assistant":
                    task.config.pop("_poll_count", None)
                    ctx._scheduler.queue.update(task)
                    return await self._complete(task, ctx, last)
        except Exception as e:
            logger.debug("_chain_continue: get_messages failed: %s", e)

        # Still running — wait 5 min then check again
        task.config["_poll_count"] = polls + 1
        task.config["session_id"] = session_id
        ctx._scheduler.queue.update(task)
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
        ctx._scheduler.queue.update(task)

        await _push_hitl_notification(ctx, task)
        return TaskResult(
            success=True,
            waiting_for_input=question_text,
            waiting_for_input_choices=options if options else None,
        )

    # ------------------------------------------------------------------
    # Resume question (Question API reply)
    # ------------------------------------------------------------------

    async def _resume_question(self, task: Task, ctx: ExecutorContext) -> "TaskResult":
        """Called after the user replies to a Question API HITL."""
        client = await self._get_client(task)
        try:
            return await self._resume_question_inner(task, ctx, client)
        finally:
            await self._cleanup(task, ctx)

    async def _resume_question_inner(self, task: Task, ctx: ExecutorContext, client) -> "TaskResult":
        cfg = task.config
        qid = cfg.get("question_id", "")
        user_reply = cfg.get("_user_reply") or cfg.get("ext_agent_reply") or cfg.get("reply_to_question", "")

        if not user_reply:
            return TaskResult(success=False, error_message="no reply found in task config")

        try:
            await client.reply_to_question(qid, user_reply)
        except Exception as e:
            return TaskResult(success=False, error_message=f"question reply failed: {e}")

        # Clear resume state, re-enter run loop
        cfg.pop("_mode", None)
        cfg.pop("question_id", None)
        cfg.pop("_user_reply", None)
        cfg.pop("ext_agent_reply", None)
        cfg.pop("reply_to_question", None)
        cfg["prompt"] = "continue"
        ctx._scheduler.queue.update(task)
        return await self._run(task, ctx)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_client(self, task: Task):
        """Get an OpenCodeClient for this task.

        Resolution order:
          1. Explicit opencode_url in task config
          2. sandbox_id/server_id → SandboxManager lookup (meta.json)
          3. working_dir → exact match against running sandboxes ONLY
          4. start_new=True → spawn a fresh OpenCode in working_dir
          5. CubeSandbox (if configured)
          6. Fail loud with clear error (no silent fallback to wrong project)

        Returns an OpenCodeClient instance.
        """
        from app.scheduler.sandbox.opencode_client import OpenCodeClient

        cfg = task.config or {}
        password = cfg.get("opencode_password") or ""

        # 1. Explicit URL wins
        url = (cfg.get("opencode_url") or "").strip()
        if url:
            client = OpenCodeClient(base_url=url, password=password)
            cfg["_opencode_client"] = client
            return client

        sandbox_key = (cfg.get("sandbox_id") or cfg.get("server_id") or "").strip()
        working_dir = (cfg.get("working_dir") or "").strip()
        start_new = bool(cfg.get("start_new", False))

        # 2. Explicit sandbox_id/server_id → SandboxManager lookup
        if sandbox_key:
            try:
                from app.sandbox.manager import SandboxManager
                mgr = SandboxManager()
                entry = mgr.get(sandbox_key)
                if entry and entry.status == "running":
                    url = f"http://127.0.0.1:{entry.port}"
                    password = entry.password or ""
                    logger.info("Using sandbox %s at %s", sandbox_key, url)
                    client = OpenCodeClient(base_url=url, password=password)
                    cfg["_opencode_client"] = client
                    return client
                if entry and entry.status != "running":
                    logger.info("Sandbox %s exists but is %s; will start fresh", sandbox_key, entry.status)
            except Exception as e:
                logger.warning("SandboxManager lookup for %s failed: %s", sandbox_key, e)

        # 3. EXACT working_dir match against running sandboxes — no fuzzy match
        if working_dir and not start_new:
            try:
                from app.sandbox.manager import SandboxManager
                mgr = SandboxManager()
                normalized = working_dir.rstrip("/")
                matches = [
                    e for e in mgr.list()
                    if e.status == "running"
                    and e.agent_type == "opencode"
                    and (e.working_dir or "").rstrip("/") == normalized
                ]
                if len(matches) == 1:
                    entry = matches[0]
                    url = f"http://127.0.0.1:{entry.port}"
                    password = entry.password or ""
                    logger.info("Matched working_dir to sandbox %s at %s", entry.sandbox_id, url)
                    client = OpenCodeClient(base_url=url, password=password)
                    cfg["_opencode_client"] = client
                    return client
                if len(matches) > 1:
                    raise RuntimeError(
                        f"Multiple running sandboxes match working_dir={working_dir}. "
                        "Specify sandbox_id explicitly to disambiguate."
                    )
                # No match — fall through to either start_new or error
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning("SandboxManager working_dir lookup failed: %s", e)

        # 4. start_new=True → spawn a fresh per-task OpenCode via OpenCodePerTaskBackend
        # Each task gets its own port (4400-4499), own log, own CWD, own password.
        # Lifecycle is tied to the task — killed in _cleanup() on task end.
        if start_new and working_dir:
            try:
                from app.scheduler.sandbox.per_task import OpenCodePerTaskBackend
                ptb = OpenCodePerTaskBackend()
                instance = ptb.spawn(task_id=task.id, working_dir=working_dir)
                cfg["_per_task_backend"] = ptb
                cfg["_per_task_instance"] = instance
                url = f"http://127.0.0.1:{instance.port}"
                password = instance.password
                logger.info(
                    "Started per-task OpenCode for %s on port %d (log: %s)",
                    task.id, instance.port, instance.log_path,
                )
                client = OpenCodeClient(base_url=url, password=password)
                cfg["_opencode_client"] = client
                return client
            except Exception as e:
                logger.error(
                    "Failed to start per-task OpenCode in %s: %s", working_dir, e
                )
                raise

        # 5. CubeSandbox (if configured and use_sandbox isn't False)
        if cfg.get("use_sandbox", True):
            try:
                from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient
                cs_client = CubeSandboxClient(template_id=cfg.get("sandbox_template"))
                cs_client.start()
                cfg["_cube_client"] = cs_client
                cfg["_owned_cube"] = True  # mark for cleanup
                if working_dir:
                    cs_client.upload_project(working_dir)
                url = cs_client.get_opencode_url()
                logger.info("CubeSandbox booted for task %s: url=%s", task.id, url)
                client = OpenCodeClient(base_url=url)
                cfg["_opencode_client"] = client
                return client
            except Exception as e:
                logger.warning("CubeSandbox unavailable (%s)", e)

        # 6. No working_dir and no sandbox_key — if start_new not set, allow localhost fallback
        if not working_dir and not sandbox_key:
            url = f"http://localhost:{os.getenv("OPENCODE_PORT", "4173")}"
            logger.warning(
                "No working_dir or sandbox_id; defaulting to %s. "
                "Pass start_new=True + working_dir to spawn a fresh OpenCode.",
                url,
            )
            client = OpenCodeClient(base_url=url, password=password)
            cfg["_opencode_client"] = client
            return client

        # 7. working_dir was given but no sandbox matched and start_new not set
        raise RuntimeError(
            f"No running sandbox matches working_dir={working_dir!r}. "
            f"Either start a sandbox for this dir (set start_new=True in config) "
            f"or pass opencode_url explicitly."
        )

    async def _sse_first_permission(self, client, session_id: str):
        """
        Subscribe to /session/{id}/event and return the first permission.asked event.
        Returns None if the stream ends without a permission.
        """
        try:
            async for perm in client.subscribe_events(session_id):
                return perm
        except Exception as e:
            logger.debug("SSE permission watcher ended: %s", e)
        return None

    async def _poll_first_hitl(self, client, session_id: str, poll_interval: float = 1.0):
        """
        Poll /permission and /question for pending requests on this session.

        Backup for the SSE event stream — newer OpenCode versions (1.17+) use
        /permission/ask and /question endpoints, not the SSE event stream.
        Polling is slower but reliable.

        Returns a dict with type ("permission" or "question") and the data, or
        None on timeout/cancel.
        """
        import asyncio as _asyncio
        deadline = _asyncio.get_event_loop().time() + 600  # 10 min max wait
        seen_perm_ids = set()
        seen_question_ids = set()
        try:
            while _asyncio.get_event_loop().time() < deadline:
                try:
                    perms = await client.list_permissions(session_id)
                    for p in perms:
                        pid = p.get("id", "")
                        if pid and pid not in seen_perm_ids:
                            seen_perm_ids.add(pid)
                            return {"type": "permission", "data": p}
                except Exception as e:
                    logger.debug("Permission poll error: %s", e)
                try:
                    questions = await client.list_questions(session_id)
                    for q in questions:
                        qid = q.get("id", "")
                        if qid and qid not in seen_question_ids:
                            seen_question_ids.add(qid)
                            return {"type": "question", "data": q}
                except Exception as e:
                    logger.debug("Question poll error: %s", e)
                await _asyncio.sleep(poll_interval)
        except _asyncio.CancelledError:
            return None
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
