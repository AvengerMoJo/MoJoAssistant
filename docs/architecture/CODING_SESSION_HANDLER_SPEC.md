# Coding Session Handler — Implementation Specification

> **Purpose:** Two parallel implementation plans (OpenCode and Goose ACP) for a
> long-running autonomous coding agent session with async completion signals and
> mid-task HITL. Implement exactly one plan; compare results.
>
> **Status:** Specification only — not yet implemented.
> **Target branch:** `wip_coding_session_handler` (create from `wip_v1.4.2`)
> **Last updated:** 2026-06-17

---

## Goal

Allow MoJoAssistant roles (e.g. PoPo) to delegate a coding task to an external
coding agent (OpenCode or Goose) as a long-running autonomous session:

1. **Fire and check later** — dispatch a task, get a `task_id`, check the result
   when done. No blocking, no polling loop in the caller.
2. **Completion signal** — when the coding agent finishes, the MoJo scheduler task
   transitions to `COMPLETED` and a HITL push notification is sent to the owner
   (Discord / ntfy).
3. **Mid-task HITL** — when the coding agent needs a decision (tool permission or
   arbitrary question), it surfaces the question through MoJo's existing HITL inbox.
   The human replies via Discord; the coding agent unblocks and continues.

---

## Background reading (read before implementing)

| File | What to read |
|---|---|
| `app/scheduler/models.py:39` | `TaskType`, `TaskStatus` enums |
| `app/scheduler/executor_registry.py:1` | `TaskHandler` ABC and `HandlerRegistry` |
| `app/scheduler/handlers/__init__.py` | How handlers are registered |
| `app/scheduler/handlers/bonsai.py` | Pattern for a two-mode handler with HITL |
| `app/scheduler/hitl_bridge.py` | `ask_user` / `check_reply` — existing HITL primitives |
| `app/mcp/core/tools.py:6513` | `external_agent` hub dispatcher |
| `app/mcp/core/tools.py:6576` | `_execute_external_agent_run_task` — how Claude Code is spawned |
| `app/mcp/core/tools.py:6685` | `_generate_claude_code_mcp_config` — MCP injection pattern |
| `submodules/coding-agent-mcp-tool/src/coding_agent_mcp/backends/opencode.py` | OpenCode backend (HTTP client, all endpoints) |
| `submodules/coding-agent-mcp-tool/tests/test_permission_flow.py` | Validated: SSE permission flow |
| `submodules/coding-agent-mcp-tool/tests/test_session_rejoin.py` | Validated: cancel → respond → rejoin works |
| `config/skill_blueprints/claude_code_session.json` | Example skill blueprint shape |
| `docs/architecture/CODING_AGENT_BRIDGES.md` | Decision rationale and route overview |

---

## Shared prerequisites

Both plans require the same two changes before handler code is written.

### Prerequisite 1 — New `TaskType.CODING_SESSION`

**File:** `app/scheduler/models.py:39`

Add one line to the `TaskType` enum:

```python
CODING_SESSION = "coding_session"  # Long-running external coding agent session
```

### Prerequisite 2 — `backend_session_run` dispatch action

**File:** `app/mcp/core/tools.py` — inside `_execute_external_agent` (around line 6556)

Add a new `action` branch that creates and enqueues a `CODING_SESSION` task:

```python
if action == "backend_session_run":
    return await self._execute_backend_session_run(args)
```

Implement `_execute_backend_session_run`:

```python
async def _execute_backend_session_run(self, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Dispatch a long-running coding session as a CODING_SESSION scheduler task.

    Required args:
      prompt       — task description
      backend_type — "opencode" | "goose"
      server_id    — which backend server to use

    Optional args:
      working_dir  — CWD for the coding agent
      task_id      — pre-assign; auto-generated if omitted
      session_id   — rejoin existing session (OpenCode only)
    """
    from app.scheduler.models import Task, TaskType, TaskStatus
    import time as _time

    prompt = (args.get("prompt") or "").strip()
    backend_type = (args.get("backend_type") or "opencode").strip()
    if not prompt:
        return {"status": "error", "message": "prompt is required"}

    task_id = (args.get("task_id") or f"cs-{int(_time.time())}").strip()
    working_dir = (args.get("working_dir") or "").strip()
    server_id = (args.get("server_id") or "").strip()
    session_id = (args.get("session_id") or "").strip()   # OpenCode rejoin

    existing = self.scheduler.queue.get(task_id)
    if existing is None:
        task = Task(
            id=task_id,
            type=TaskType.CODING_SESSION,
            status=TaskStatus.PENDING,
            description=f"[{backend_type}] {prompt[:80]}",
            config={
                "backend_type": backend_type,
                "server_id": server_id,
                "prompt": prompt,
                "working_dir": working_dir,
                "session_id": session_id,
            },
        )
        self.scheduler.queue.add(task)

    return {
        "status": "dispatched",
        "task_id": task_id,
        "backend_type": backend_type,
        "monitor_with": f'scheduler(action="get", task_id="{task_id}")',
    }
```

Also add the help text entry for this action in the `HELP` dict near line 995:
```
"action='backend_session_run', prompt, backend_type?, server_id?, working_dir?, task_id?, session_id? — dispatch a long-running coding session task"
```

---

## Plan A — OpenCode handler

### Overview

The handler runs `send_message` (blocking HTTP POST, 300 s timeout) in a background
asyncio task while a parallel SSE listener watches for permission requests at
`GET /session/{id}/event`. If a permission fires, the handler saves state and
exits, leaving the task in `WAITING_FOR_INPUT`. When the user replies, the handler
is re-entered (rejoin mode) and continues the session.

### A.1 — Create `app/scheduler/handlers/coding_session_opencode.py`

```python
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
from typing import Any, Dict, Optional

from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult, TaskStatus, TaskType

logger = logging.getLogger(__name__)

# Seconds before re-chaining on timeout (keep under backend MESSAGE_TIMEOUT=300)
_CHAIN_THRESHOLD = 290.0


class OpenCodeSessionHandler(TaskHandler):

    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        cfg = task.config or {}
        mode = cfg.get("_mode", "run")

        if mode == "resume":
            return await self._resume(task, ctx)
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
                    output={"error": f"OpenCode create_session returned no ID: {session}"},
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

        done, pending = await asyncio.wait(
            [task_send, task_sse],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Case 1: SSE permission arrived before send_message returned
        if task_sse in done and task_sse not in [t for t in pending]:
            exc = task_sse.exception()
            if exc is None:
                perm = task_sse.result()
                if perm is not None:
                    task_send.cancel()
                    try:
                        await task_send
                    except (asyncio.CancelledError, Exception):
                        pass
                    return await self._handle_permission(task, ctx, perm)

        # Case 2: send_message returned (may have finished before any permission)
        if task_send in done:
            task_sse.cancel()
            exc = task_send.exception()
            if exc is not None:
                # Timeout → chain continuation
                if "timed out" in str(exc).lower() or "ReadTimeout" in type(exc).__name__:
                    return await self._chain_continue(task, ctx, backend, session_id)
                return TaskResult(success=False, output={"error": str(exc)})
            result = task_send.result()
            return await self._complete(task, ctx, result)

        # Fallback: neither done in expected way
        for t in pending:
            t.cancel()
        return TaskResult(success=False, output={"error": "unexpected wait state"})

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
        user_reply = cfg.get("_user_reply", "once")

        # Translate user reply to OpenCode permission response
        reply = _map_user_reply_to_permission(user_reply)

        try:
            await backend.respond_to_permission(
                cfg["session_id"], perm_id, reply, directory=perm_dir
            )
        except Exception as e:
            return TaskResult(success=False, output={"error": f"respond_to_permission failed: {e}"})

        # Clear resume state, re-enter run loop with "continue" prompt
        cfg.pop("_mode", None)
        cfg.pop("perm_id", None)
        cfg.pop("perm_directory", None)
        cfg.pop("_user_reply", None)
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

        # Push HITL notification (same channel as bonsai pin review)
        await _push_hitl_notification(ctx, task)

        # Return a non-terminal result; scheduler will not re-run WAITING_FOR_INPUT tasks
        return TaskResult(
            success=True,
            output={"status": "waiting_for_permission", "perm_id": perm_id},
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
            questions = await backend._client.get("/question")
            questions.raise_for_status()
            for q in (questions.json() or []):
                if q.get("sessionID") == session_id:
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
        return TaskResult(success=True, output={"result": summary, "raw": result})

    async def _chain_continue(
        self, task: Task, ctx: ExecutorContext, backend, session_id: str
    ) -> TaskResult:
        """
        send_message timed out. Check if there's a pending question before chaining.
        """
        q = await self._poll_questions(backend, session_id)
        if q:
            return await self._handle_question_hitl(task, ctx, q)

        # No question — chain "continue" to next invocation
        task.config["prompt"] = "continue where you left off"
        task.config["session_id"] = session_id
        task.status = TaskStatus.PENDING
        ctx.queue.update(task)
        logger.info("OpenCodeSessionHandler: chaining 'continue' for task %s", task.id)
        return TaskResult(success=True, output={"status": "chained"})

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
            output={"status": "waiting_for_question_reply", "question_id": qid},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_backend(self, task: Task):
        from coding_agent_mcp.backends import BackendRegistry
        from coding_agent_mcp.config.loader import load_config
        cfg_obj = load_config()
        reg = BackendRegistry()
        reg.reload(cfg_obj.servers, cfg_obj.default_server)
        server_id = task.config.get("server_id") or ""
        return reg.get(server_id) if server_id else reg.get_default()

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
```

### A.2 — Resume routing

When a user replies to a HITL inbox item for a `CODING_SESSION` task, the
existing `resume_task_with_reply` machinery sets `task.config["ext_agent_reply"]`
and keeps the task `RUNNING`. This handler needs to intercept that reply.

**File:** `app/scheduler/handlers/coding_session_opencode.py` — add to `execute`:

```python
# Handle reply-to-question (Question API) resume
if mode == "resume_question":
    return await self._resume_question(task, ctx)
```

```python
async def _resume_question(self, task: Task, ctx: ExecutorContext) -> TaskResult:
    backend = self._get_backend(task)
    cfg = task.config
    qid = cfg.get("question_id", "")
    user_reply = cfg.get("_user_reply") or cfg.get("ext_agent_reply", "")

    if not user_reply:
        return TaskResult(success=False, output={"error": "no reply found in task config"})

    try:
        await backend._client.post(
            f"/question/{qid}/reply",
            json={"answers": [[user_reply]]},
        )
    except Exception as e:
        return TaskResult(success=False, output={"error": f"question reply failed: {e}"})

    # Clear resume state, re-enter run loop
    cfg.pop("_mode", None)
    cfg.pop("question_id", None)
    cfg.pop("_user_reply", None)
    cfg.pop("ext_agent_reply", None)
    cfg["prompt"] = "continue"
    ctx.queue.update(task)
    return await self._run(task, ctx)
```

### A.3 — Helper functions (add at module bottom)

```python
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
        from app.scheduler.handlers.bonsai import _notify_owner  # reuse bonsai pattern
        await _notify_owner(ctx, task.pending_question or "", task.id)
    except Exception as e:
        logger.warning("HITL push failed for task %s: %s", task.id, e)


async def _push_completion_notification(
    ctx: ExecutorContext, task: Task, summary: str
) -> None:
    """Send a completion push notification."""
    try:
        from app.scheduler.handlers.bonsai import _notify_owner
        msg = f"Coding task complete [{task.id}]:\n{summary[:300]}"
        await _notify_owner(ctx, msg, task.id)
    except Exception as e:
        logger.warning("Completion push failed for task %s: %s", task.id, e)
```

> **Note:** If `_notify_owner` is not importable from bonsai, replicate the
> ntfy/Discord notification pattern used there. Do not invent a new channel.

### A.4 — Register the handler

**File:** `app/scheduler/handlers/__init__.py`

```python
from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler
# ... in build_registry():
registry.register(TaskType.CODING_SESSION, OpenCodeSessionHandler())
```

### A.5 — Expose via `external_agent` action

The `backend_session_run` action added in Prerequisite 2 dispatches to this
handler automatically via the scheduler.

Optionally add a convenience `backend_session_run_opencode` action that defaults
`backend_type="opencode"` — not required.

### A.6 — Acceptance criteria (OpenCode)

- [ ] `external_agent(action="backend_session_run", prompt="write hello.py", backend_type="opencode")` returns `{status: "dispatched", task_id: "..."}` immediately
- [ ] `scheduler(action="get", task_id="...")` shows `status=running` while the session is active
- [ ] When OpenCode requests a permission, MoJo sets `status=waiting_for_input` and the `pending_question` field contains the permission description
- [ ] Replying via `reply_to_task(task_id=..., reply="once")` causes the session to continue
- [ ] When OpenCode's LLM asks a structured question (Question API), it surfaces in `pending_question` with options
- [ ] On completion, `status=completed`, `output` contains the agent's final response text
- [ ] A Discord / ntfy notification is sent on completion and on each HITL pause
- [ ] If `send_message` times out at 300 s, a "continue" chain is dispatched and the task stays `running`
- [ ] `test_permission_flow.py` and `test_session_rejoin.py` still pass (no regressions in backend)

---

## Plan B — Goose ACP handler

### Overview

The handler creates a Goose session via `POST /agent/start` with MoJo injected
as an HTTP MCP server in `extension_overrides`. An asyncio task holds the SSE
stream open, routing `Finish` events to task completion and `Message` events
to a pending-confirmation detector. Arbitrary HITL questions are handled natively
by Goose calling MoJo's `ask_user` tool (since MoJo is its MCP server).

### B.1 — Add `GooseBackend` to the submodule

**File:** `submodules/coding-agent-mcp-tool/src/coding_agent_mcp/backends/goose.py` (new)

The Goose backend does not implement the `send_message` blocking pattern. Instead
it uses SSE. The backend wraps only the REST management operations; the SSE
lifecycle is managed by the handler (not the backend) because it requires asyncio
task coordination.

```python
"""Goose coding agent backend (goosed daemon)."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from coding_agent_mcp.backends.base import AgentBackend
from coding_agent_mcp.config.models import ServerEntry

logger = logging.getLogger(__name__)
DEFAULT_TIMEOUT = 30.0


class GooseBackend(AgentBackend):
    """
    Wraps a running goosed daemon (block/goose).

    This backend implements the AgentBackend interface for session management
    operations. SSE streaming is handled externally in GooseSessionHandler.
    """

    backend_type = "goose"

    def __init__(self, server_id: str, base_url: str, api_key: str = "") -> None:
        self._server_id = server_id
        self._base_url = base_url.rstrip("/")
        headers: dict = {"Content-Type": "application/json"}
        if api_key:
            headers["X-Secret-Key"] = api_key
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )

    @classmethod
    def from_config(cls, entry: ServerEntry) -> GooseBackend:
        return cls(
            server_id=entry.id,
            base_url=entry.url,
            password=entry.password or "",
        )

    async def health(self) -> dict:
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return {"status": "ok", "backend_type": "goose", "server_id": self._server_id}

    async def create_session(self, **kwargs: Any) -> dict:
        """
        POST /agent/start

        Optional kwargs:
          working_dir        — str
          mojo_mcp_url       — str  (HTTP MCP URL for MoJo injection)
          mojo_mcp_api_key   — str
          extension_overrides — list[dict]  (raw ExtensionConfig list)
        """
        extension_overrides = kwargs.get("extension_overrides") or []

        mojo_url = kwargs.get("mojo_mcp_url", "")
        if mojo_url and not any(e.get("name") == "mojo" for e in extension_overrides):
            mcp_entry: dict = {
                "type": "StreamableHttp",
                "name": "mojo",
                "description": "MoJoAssistant — HITL, memory, task management",
                "uri": mojo_url.rstrip("/") + "/",
                "envs": {},
                "timeout": 30,
            }
            if kwargs.get("mojo_mcp_api_key"):
                mcp_entry["headers"] = {"MCP-API-Key": kwargs["mojo_mcp_api_key"]}
            extension_overrides.append(mcp_entry)

        body: dict = {"extension_overrides": extension_overrides}
        if kwargs.get("working_dir"):
            body["working_dir"] = kwargs["working_dir"]

        resp = await self._client.post("/agent/start", json=body)
        resp.raise_for_status()
        return resp.json()

    async def list_sessions(self) -> list[dict]:
        resp = await self._client.get("/sessions")
        resp.raise_for_status()
        return resp.json()

    async def get_session(self, session_id: str) -> dict:
        resp = await self._client.get(f"/sessions/{session_id}")
        resp.raise_for_status()
        return resp.json()

    async def delete_session(self, session_id: str) -> dict:
        resp = await self._client.delete(f"/sessions/{session_id}")
        resp.raise_for_status()
        return resp.json()

    async def send_message(self, session_id: str, content: str, **kwargs: Any) -> dict:
        """
        Synchronous send via POST /reply (holds SSE open).
        For the handler's async lifecycle use stream_reply() instead.
        """
        raise NotImplementedError(
            "GooseBackend does not support blocking send_message. "
            "Use GooseSessionHandler which manages SSE directly."
        )

    async def get_messages(self, session_id: str) -> list[dict]:
        resp = await self._client.get(f"/sessions/{session_id}/messages")
        resp.raise_for_status()
        return resp.json()

    async def resume_session(self, session_id: str) -> dict:
        """POST /agent/resume — reconnect after goosed restart."""
        resp = await self._client.post(
            "/agent/resume",
            json={"session_id": session_id, "load_model_and_extensions": True},
        )
        resp.raise_for_status()
        return resp.json()

    async def confirm_tool(
        self, session_id: str, request_id: str, action: str = "AllowOnce"
    ) -> dict:
        """
        POST /action-required/tool-confirmation

        action: "AllowOnce" | "AllowSession" | "Deny"
        """
        resp = await self._client.post(
            "/action-required/tool-confirmation",
            json={
                "id": request_id,
                "principal_type": "Tool",
                "action": action,
                "session_id": session_id,
            },
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def cancel_session(self, session_id: str, request_id: str) -> dict:
        resp = await self._client.post(
            f"/sessions/{session_id}/cancel",
            json={"request_id": request_id},
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def close(self) -> None:
        try:
            self._client._transport.close()  # type: ignore[union-attr]
        except Exception:
            pass
```

Register `GooseBackend` in
`submodules/coding-agent-mcp-tool/src/coding_agent_mcp/backends/__init__.py`
(follow the same pattern as `OpenCodeBackend`).

### B.2 — Create `app/scheduler/handlers/coding_session_goose.py`

```python
"""
Goose ACP coding session handler.

Lifecycle:
  PENDING   → POST /agent/start (with MoJo as MCP server) → hold SSE stream
  SSE Finish → COMPLETED + push notification
  SSE Message with tool confirmation pending → WAITING_FOR_INPUT + push notification
  user replies → POST /action-required/tool-confirmation → SSE continues
  SSE drop  → attempt reconnect via POST /agent/resume + GET /sessions/{id}/events

Arbitrary HITL (questions, not just tool confirmations):
  Goose LLM calls MoJo's ask_user tool (MoJo is injected as MCP server).
  This routes through the existing hitl_bridge.ask_user() / check_reply() flow.
  No special handling needed in this handler for that case.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator, Dict, Optional, Tuple

from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult, TaskStatus

logger = logging.getLogger(__name__)

# Reconnect: max attempts on SSE drop before marking failed
_MAX_RECONNECT = 3
# Heartbeat interval from goosed is 500 ms; declare dead after 10 s of silence
_SSE_IDLE_TIMEOUT = 10.0


class GooseSessionHandler(TaskHandler):

    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        cfg = task.config or {}
        mode = cfg.get("_mode", "run")

        if mode == "resume_tool_confirm":
            return await self._resume_tool_confirm(task, ctx)
        return await self._run(task, ctx)

    # ------------------------------------------------------------------
    # Run mode
    # ------------------------------------------------------------------

    async def _run(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        backend = self._get_backend(task)
        cfg = task.config

        # Create session if new; resume if we have a session_id (after reconnect)
        session_id = cfg.get("session_id", "")
        if not session_id:
            mojo_url = _mojo_mcp_url()
            mojo_key = os.getenv("MCP_API_KEY", "")
            session = await backend.create_session(
                working_dir=cfg.get("working_dir", ""),
                mojo_mcp_url=mojo_url,
                mojo_mcp_api_key=mojo_key,
            )
            session_id = (
                session.get("id")
                or session.get("session_id")
                or (session.get("session") or {}).get("id", "")
            )
            if not session_id:
                return TaskResult(
                    success=False,
                    output={"error": f"goused start returned no session ID: {session}"},
                )
            cfg["session_id"] = session_id
            cfg["_reconnect_attempts"] = 0
            ctx.queue.update(task)

        prompt = cfg.get("prompt", "")
        return await self._stream_reply(task, ctx, backend, session_id, prompt)

    # ------------------------------------------------------------------
    # SSE stream runner
    # ------------------------------------------------------------------

    async def _stream_reply(
        self,
        task: Task,
        ctx: ExecutorContext,
        backend,
        session_id: str,
        prompt: str,
    ) -> TaskResult:
        """
        POST /reply with SSE response, process events until Finish or interruption.
        """
        import httpx

        last_event_id: Optional[str] = task.config.get("_last_event_id")
        request_id: Optional[str] = None

        url = f"{backend._base_url}/reply"
        body = {
            "session_id": session_id,
            "user_message": {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            },
        }

        headers = dict(backend._client.headers)
        if last_event_id:
            headers["Last-Event-ID"] = last_event_id

        try:
            async with backend._client.stream(
                "POST", "/reply", json=body, headers=headers, timeout=None
            ) as resp:
                resp.raise_for_status()
                async for event_id, event_type, data in _parse_sse(resp):
                    if event_id:
                        task.config["_last_event_id"] = event_id
                        ctx.queue.update(task)

                    if event_type == "Ping":
                        continue

                    if event_type == "Finish":
                        reason = data.get("reason", "")
                        token_state = data.get("token_state", {})
                        summary = _extract_finish_summary(data)
                        await _push_completion_notification(ctx, task, summary)
                        return TaskResult(
                            success=True,
                            output={
                                "result": summary,
                                "finish_reason": reason,
                                "token_state": token_state,
                            },
                        )

                    if event_type == "Error":
                        return TaskResult(
                            success=False,
                            output={"error": data.get("error", "Goose returned Error event")},
                        )

                    if event_type == "Message":
                        # Detect pending tool confirmation inside the message
                        confirm = _detect_tool_confirmation(data)
                        if confirm:
                            request_id = confirm["id"]
                            task.config["_mode"] = "resume_tool_confirm"
                            task.config["_request_id"] = request_id
                            task.config["_session_id_active"] = session_id
                            task.status = TaskStatus.WAITING_FOR_INPUT
                            task.pending_question = (
                                f"Goose wants to use tool: {confirm.get('tool', 'unknown')}\n"
                                f"Reply: allow / allow_session / deny"
                            )
                            ctx.queue.update(task)
                            await _push_hitl_notification(ctx, task)
                            # Return non-terminal — scheduler will not re-run WAITING tasks
                            return TaskResult(
                                success=True,
                                output={"status": "waiting_for_tool_confirm", "request_id": request_id},
                            )

                    if event_type == "ActiveRequests":
                        ids = data.get("request_ids", [])
                        if ids:
                            request_id = ids[-1]

        except (httpx.RemoteProtocolError, httpx.ReadError, asyncio.CancelledError) as e:
            return await self._handle_sse_drop(task, ctx, backend, session_id, e)
        except Exception as e:
            return TaskResult(success=False, output={"error": f"SSE stream error: {e}"})

        return TaskResult(success=False, output={"error": "SSE stream ended without Finish"})

    # ------------------------------------------------------------------
    # Tool confirmation resume
    # ------------------------------------------------------------------

    async def _resume_tool_confirm(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        backend = self._get_backend(task)
        cfg = task.config

        session_id = cfg.get("session_id", "")
        request_id = cfg.get("_request_id", "")
        user_reply = cfg.get("_user_reply") or cfg.get("ext_agent_reply", "allow")

        action = _map_reply_to_goose_action(user_reply)

        try:
            await backend.confirm_tool(session_id, request_id, action)
        except Exception as e:
            return TaskResult(success=False, output={"error": f"confirm_tool failed: {e}"})

        # Clear resume state and continue streaming
        cfg.pop("_mode", None)
        cfg.pop("_request_id", None)
        cfg.pop("_user_reply", None)
        cfg.pop("ext_agent_reply", None)
        cfg["prompt"] = ""   # empty prompt = continue (no new user message)
        ctx.queue.update(task)

        return await self._stream_reply(task, ctx, backend, session_id, "")

    # ------------------------------------------------------------------
    # SSE drop / reconnect
    # ------------------------------------------------------------------

    async def _handle_sse_drop(
        self, task: Task, ctx: ExecutorContext, backend, session_id: str, exc: Exception
    ) -> TaskResult:
        attempts = task.config.get("_reconnect_attempts", 0)
        if attempts >= _MAX_RECONNECT:
            return TaskResult(
                success=False,
                output={"error": f"SSE dropped after {_MAX_RECONNECT} reconnect attempts: {exc}"},
            )

        task.config["_reconnect_attempts"] = attempts + 1
        ctx.queue.update(task)
        logger.warning(
            "GooseSessionHandler: SSE drop for task %s (attempt %d/%d): %s",
            task.id, attempts + 1, _MAX_RECONNECT, exc,
        )

        try:
            await backend.resume_session(session_id)
        except Exception as resume_exc:
            logger.warning("resume_session failed: %s", resume_exc)

        # Re-enter stream with Last-Event-ID for replay
        await asyncio.sleep(2.0)
        return await self._stream_reply(task, ctx, backend, session_id, "")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_backend(self, task: Task):
        from coding_agent_mcp.backends import BackendRegistry
        from coding_agent_mcp.config.loader import load_config
        cfg_obj = load_config()
        reg = BackendRegistry()
        reg.reload(cfg_obj.servers, cfg_obj.default_server)
        server_id = task.config.get("server_id", "")
        return reg.get(server_id) if server_id else reg.get_default()
```

### B.3 — SSE parsing and helper functions (add at module bottom)

```python
async def _parse_sse(
    resp,
) -> AsyncIterator[Tuple[Optional[str], str, Dict[str, Any]]]:
    """
    Yield (event_id, event_type, data_dict) from an httpx streaming SSE response.
    Handles multi-line data fields and id/event fields per SSE spec.
    """
    event_id: Optional[str] = None
    event_type: str = "message"
    data_lines: list[str] = []

    async for line in resp.aiter_lines():
        line = line.rstrip("\r")
        if line == "":
            # Dispatch event
            if data_lines:
                raw = "\n".join(data_lines)
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = {"raw": raw}
                yield event_id, event_type, parsed
            # Reset
            event_id = None
            event_type = "message"
            data_lines = []
        elif line.startswith("id:"):
            event_id = line[3:].strip()
        elif line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())


def _detect_tool_confirmation(message_event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse a Goose Message SSE event for pending tool confirmation requests.

    Goose embeds tool call information in the message content. This function
    returns a dict with {"id": request_id, "tool": tool_name} if a confirmation
    is detected, otherwise None.

    NOTE: The exact message structure for tool confirmations is not yet
    confirmed from Goose source. Implement a best-effort parser and log
    the full event at DEBUG level so the structure can be refined from
    real session transcripts.
    """
    logger.debug("Goose Message event: %s", json.dumps(message_event)[:500])

    # Best-effort: look for tool_call or action_required markers in message content
    content = message_event.get("message", {}).get("content", [])
    for block in (content if isinstance(content, list) else []):
        if isinstance(block, dict):
            if block.get("type") == "tool_use" and block.get("awaiting_confirmation"):
                return {"id": block.get("id", ""), "tool": block.get("name", "")}
    return None


def _extract_finish_summary(data: Dict[str, Any]) -> str:
    reason = data.get("reason", "")
    msg = data.get("message", {})
    if isinstance(msg, dict):
        for block in (msg.get("content") or []):
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", reason)
    return reason


def _mojo_mcp_url() -> str:
    port = int(os.getenv("SERVER_PORT", "8000"))
    base = os.getenv("MOJO_BASE_URL", f"http://localhost:{port}")
    return base.rstrip("/") + "/"


def _map_reply_to_goose_action(reply: str) -> str:
    r = reply.lower().strip()
    if r in ("allow_session", "always"):
        return "AllowSession"
    if r in ("deny", "no", "reject"):
        return "Deny"
    return "AllowOnce"


async def _push_hitl_notification(ctx: ExecutorContext, task: Task) -> None:
    try:
        from app.scheduler.handlers.bonsai import _notify_owner
        await _notify_owner(ctx, task.pending_question or "", task.id)
    except Exception as e:
        logger.warning("HITL push failed for task %s: %s", task.id, e)


async def _push_completion_notification(
    ctx: ExecutorContext, task: Task, summary: str
) -> None:
    try:
        from app.scheduler.handlers.bonsai import _notify_owner
        msg = f"Goose coding task complete [{task.id}]:\n{summary[:300]}"
        await _notify_owner(ctx, msg, task.id)
    except Exception as e:
        logger.warning("Completion push failed for task %s: %s", task.id, e)
```

### B.4 — Register the handler

**File:** `app/scheduler/handlers/__init__.py`

Register Goose alongside OpenCode for the same `TaskType.CODING_SESSION`.
The dispatcher selects the right handler based on `task.config["backend_type"]`.

Extend `build_registry` to route by backend type:

```python
from app.scheduler.handlers.coding_session_opencode import OpenCodeSessionHandler
from app.scheduler.handlers.coding_session_goose import GooseSessionHandler

# In build_registry():
from app.scheduler.handlers.coding_session_router import CodingSessionRouter
registry.register(TaskType.CODING_SESSION, CodingSessionRouter(
    opencode=OpenCodeSessionHandler(),
    goose=GooseSessionHandler(),
))
```

Create `app/scheduler/handlers/coding_session_router.py`:

```python
"""Routes CODING_SESSION tasks to the correct backend handler."""
from __future__ import annotations
from app.scheduler.executor_registry import ExecutorContext, TaskHandler
from app.scheduler.models import Task, TaskResult


class CodingSessionRouter(TaskHandler):
    def __init__(self, opencode: TaskHandler, goose: TaskHandler) -> None:
        self._handlers = {"opencode": opencode, "goose": goose}

    async def execute(self, task: Task, ctx: ExecutorContext) -> TaskResult:
        backend_type = (task.config or {}).get("backend_type", "opencode")
        handler = self._handlers.get(backend_type)
        if handler is None:
            return TaskResult(
                success=False,
                output={"error": f"Unknown backend_type '{backend_type}'. Use: opencode, goose"},
            )
        return await handler.execute(task, ctx)
```

### B.5 — Acceptance criteria (Goose)

- [ ] `external_agent(action="backend_session_run", prompt="...", backend_type="goose")` returns `{status: "dispatched", task_id: "..."}` immediately
- [ ] The handler calls `POST /agent/start` with `extension_overrides` containing `{type: "StreamableHttp", name: "mojo", uri: "http://localhost:8000/"}` — verifiable from goused logs
- [ ] MoJo tools (`ask_user`, `check_reply`) are accessible inside the Goose session — the Goose LLM can call them
- [ ] On `Finish` SSE event, task transitions to `completed` with output containing the finish summary
- [ ] On tool confirmation request (detected in Message event), task transitions to `waiting_for_input`
- [ ] User replies "allow" / "deny" → `POST /action-required/tool-confirmation` is called → SSE continues
- [ ] If SSE drops, handler attempts `POST /agent/resume` + reconnect up to 3 times
- [ ] `Last-Event-ID` is tracked per event and sent on reconnect
- [ ] A Discord / ntfy notification is sent on completion and each HITL pause
- [ ] `_detect_tool_confirmation` logs Message events at DEBUG level — structure can be refined after first real session

---

## Known unknowns (document findings when resolved)

| Item | Plan | Status |
|---|---|---|
| Does `POST /prompt_async` (204) require a separate `/event` SSE connection, or does `/session/{id}/event` alone give completion events? | OpenCode | Unconfirmed — needs live test |
| Exact JSON shape of a Goose Message event containing a tool confirmation request | Goose | Unconfirmed — `_detect_tool_confirmation` is best-effort; refine from transcripts |
| Does Goose's `GET /sessions/{id}/events` SSE replay (Last-Event-ID) actually work end-to-end in current goosed? | Goose | Unconfirmed — test with a real drop |
| Can `POST /reply` accept an empty prompt (for "continue after tool confirm") or does it require a non-empty user message? | Goose | Unconfirmed |
| OpenCode: does `GET /question` return questions for all sessions or only the active one? | OpenCode | Partially confirmed — filter by `sessionID` in polling loop |

---

## What NOT to implement

- Do not modify `app/scheduler/hitl_bridge.py` — it already handles arbitrary
  question HITL for both plans (MoJo as MCP server).
- Do not change `OpenCodeBackend.send_message` — the blocking path remains for
  `CodingAgentExecutor` (Popo). The handler manages the async lifecycle above it.
- Do not add retry logic inside `send_message` or `GooseBackend` — retries and
  chaining belong in the handler, not the backend.
- Do not implement multi-backend fan-out or comparison logic — one handler
  per backend, routed by `backend_type`.
