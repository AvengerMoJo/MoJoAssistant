"""
OpenCode HTTP client — direct httpx calls to OpenCode's REST API.

Replaces coding-agent-mcp-tool's OpenCodeBackend. Works with OpenCode running
inside a CubeSandbox VM (via proxy URL) or directly on the host.

Two API generations coexist in the fleet as of 2026-09-23 -- `bun install -g
opencode-ai` pulls whatever's latest, and opencode's v2 API shipped this
week. evo-x3/siliconnode1/the bootstrapped MoJoAssistant backend are all
still v1.18.x; stonemojo came pre-installed with v2.0.14. Rather than pin
every host to v1 forever, this client supports both via api_version,
discovered from OpenAPI diffing against a live v2 host (stonemojo) --
verified endpoint-by-endpoint against a real server, not guessed from docs.

v1 API surface (all under base_url with BasicAuth, not actually enforced):
  POST /session                              → create session
  GET  /session                              → list sessions
  GET  /session/{id}                         → get session
  DELETE /session/{id}                       → delete session
  POST /session/{id}/message                 → send message, body {"parts":[...]}
  GET  /session/{id}/message                 → get messages
  GET  /permission                           → list pending permissions (global)
  POST /permission/{id}/reply                → respond to permission
  GET  /question                             → list pending questions (global)
  POST /question/{id}/reply                  → answer question, body {"answers": [[...]]}
  POST /question/{id}/reject                 → reject question
  GET  /session/{id}/event                   → SSE stream (permissions + questions)

v2 API surface (all under base_url + /api, BasicAuth actually enforced,
every response wrapped in {"data": ...}):
  POST /api/session                          → create session
  GET  /api/session                          → list sessions
  GET  /api/session/{id}                     → get session
  DELETE /api/session/{id}                   → delete session
  POST /api/session/{id}/prompt              → send message, body {"text": "..."}
  GET  /api/session/{id}/message             → get messages
  GET  /api/session/{id}/permission          → list pending permissions (session-scoped)
  POST /api/session/{id}/permission/{rid}/reply → respond to permission
  GET  /api/session/{id}/form                → list pending "questions" (now "forms")
  POST /api/session/{id}/form/{fid}/reply    → answer form, body {"answer": {field_key: value}}
  GET  /api/event                            → SSE stream (global, not session-scoped)

"Question" doesn't exist in v2 -- "Form" (id prefix frm_, has a `fields`
array) is the real replacement, more general (supports multiple typed
fields, not just one string). The adapter here answers only the form's
first field, matching v1's single-question shape; a genuinely multi-field
form needs a richer caller, not something this shim can paper over.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

MESSAGE_TIMEOUT = 300.0
DEFAULT_TIMEOUT = 30.0


class OpenCodeClient:
    """Async HTTP client for OpenCode server, v1 or v2.

    Args:
        base_url: OpenCode server URL (e.g. http://localhost:4173 or CubeSandbox proxy)
        password: Basic auth password (username is always "opencode"). v1
            servers don't actually check it; v2 servers do -- always send it.
        api_version: "v1" (default, matches the existing fleet) or "v2".
    """

    def __init__(
        self,
        base_url: str,
        password: Optional[str] = None,
        api_version: str = "v1",
    ) -> None:
        if api_version not in ("v1", "v2"):
            raise ValueError(f"api_version must be 'v1' or 'v2', got {api_version!r}")
        self._base_url = base_url.rstrip("/")
        self._auth = httpx.BasicAuth("opencode", password or "")
        self._client: Optional[httpx.AsyncClient] = None
        self._v2 = api_version == "v2"
        self._prefix = "/api" if self._v2 else ""

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                auth=self._auth,
                timeout=DEFAULT_TIMEOUT,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _unwrap(self, resp: httpx.Response) -> Any:
        """v2 wraps every response in {"data": ...}; v1 returns the bare
        value. Unwrap once here so every method below reads the same
        shape regardless of api_version."""
        if not resp.content or not resp.content.strip():
            return None
        body = resp.json()
        if self._v2 and isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def health(self) -> Dict[str, Any]:
        client = await self._get_client()
        resp = await client.get("/")
        resp.raise_for_status()
        return {"status": "ok", "url": self._base_url}

    async def create_session(self, **kwargs: Any) -> Dict[str, Any]:
        client = await self._get_client()
        # v1 accepts a bodyless POST (defaults to no kwargs -> None); v2
        # requires an actual JSON body, even an empty {}, or it 400s --
        # found live 2026-09-23 against a real v2 server.
        body = kwargs if self._v2 else (kwargs or None)
        resp = await client.post(f"{self._prefix}/session", json=body)
        resp.raise_for_status()
        return self._unwrap(resp)

    async def list_sessions(self) -> List[Dict[str, Any]]:
        client = await self._get_client()
        resp = await client.get(f"{self._prefix}/session")
        resp.raise_for_status()
        return self._unwrap(resp) or []

    async def get_session(self, session_id: str) -> Dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(f"{self._prefix}/session/{session_id}")
        resp.raise_for_status()
        return self._unwrap(resp)

    async def delete_session(self, session_id: str) -> Dict[str, Any]:
        client = await self._get_client()
        resp = await client.delete(f"{self._prefix}/session/{session_id}")
        resp.raise_for_status()
        return self._unwrap(resp)

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_message(
        self, session_id: str, content: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """Send a message and block until the assistant's reply is ready.

        v1's POST /session/{id}/message is synchronous: it blocks server-side
        and its response IS the assistant's reply (shape: {"parts": [...]}).

        v2's POST /session/{id}/prompt is NOT synchronous -- confirmed live
        2026-09-23 against a real v2 server: it returns in ~0.25s with just
        an echo of the submitted user message (type "user"), while the real
        reply streams in separately and only becomes readable via
        GET /session/{id}/message, marked done by a later {"type": "idle",
        "outcome": ...} entry. To keep this method's contract identical for
        both versions (so callers -- the whole HITL-race/timeout-chaining
        flow in coding_session_opencode.py -- don't need version-aware
        logic), v2 polls internally and reshapes the result to v1's
        {"parts": [...]} shape (v2 assistant messages use ".content[]" with
        mixed "reasoning"/"text" blocks instead of v1's ".parts[]").
        """
        client = await self._get_client()
        if self._v2:
            return await self._send_message_v2(session_id, content, **kwargs)
        path = "/session/{}/message".format(session_id)
        payload = {"parts": [{"type": "text", "text": content}], **kwargs}
        resp = await client.post(path, json=payload, timeout=MESSAGE_TIMEOUT)
        resp.raise_for_status()
        return self._unwrap(resp)

    async def _send_message_v2(
        self, session_id: str, content: str, poll_interval: float = 1.5, **kwargs: Any
    ) -> Dict[str, Any]:
        client = await self._get_client()
        path = f"{self._prefix}/session/{session_id}/prompt"
        payload: Dict[str, Any] = {"text": content, **kwargs}
        resp = await client.post(path, json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        ack = self._unwrap(resp) or {}
        since = (ack.get("time") or {}).get("created", 0)

        deadline = asyncio.get_event_loop().time() + MESSAGE_TIMEOUT
        while True:
            if asyncio.get_event_loop().time() >= deadline:
                raise TimeoutError(
                    f"OpenCode v2 session {session_id}: no reply within {MESSAGE_TIMEOUT}s"
                )
            messages = await self.get_messages(session_id)
            went_idle = any(
                m.get("type") == "idle" and (m.get("time") or {}).get("created", 0) >= since
                for m in messages
            )
            if went_idle:
                reply = self._latest_assistant_message(messages, since)
                return self._v2_message_to_v1_shape(reply) if reply else {"parts": []}
            await asyncio.sleep(poll_interval)

    @staticmethod
    def _latest_assistant_message(
        messages: List[Dict[str, Any]], since: Any
    ) -> Optional[Dict[str, Any]]:
        candidates = [
            m for m in messages
            if m.get("type") == "assistant" and (m.get("time") or {}).get("created", 0) >= since
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda m: (m.get("time") or {}).get("created", 0))

    @staticmethod
    def _v2_message_to_v1_shape(message: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a v2 assistant message (".content[]", mixed block types)
        into v1's shape (".parts[]", text blocks only) so _extract_text()
        and other v1-shaped callers work unchanged."""
        parts = [
            {"type": "text", "text": block.get("text", "")}
            for block in (message.get("content") or [])
            if block.get("type") == "text"
        ]
        return {**message, "parts": parts}

    async def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        client = await self._get_client()
        resp = await client.get(f"{self._prefix}/session/{session_id}/message")
        resp.raise_for_status()
        return self._unwrap(resp) or []

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    async def list_permissions(self, session_id: str) -> List[Dict[str, Any]]:
        client = await self._get_client()
        if self._v2:
            # Already session-scoped -- no client-side filtering needed.
            resp = await client.get(f"{self._prefix}/session/{session_id}/permission")
            resp.raise_for_status()
            return self._unwrap(resp) or []
        resp = await client.get("/permission")
        resp.raise_for_status()
        if not resp.content or not resp.content.strip():
            return []
        all_perms = resp.json()
        if not isinstance(all_perms, list):
            return []
        return [p for p in all_perms if p.get("sessionID") == session_id]

    async def respond_to_permission(
        self,
        session_id: str,
        permission_id: str,
        response: str,
        directory: str = "",
    ) -> Dict[str, Any]:
        if response not in ("once", "always", "reject"):
            raise ValueError(
                f"Invalid permission response '{response}': must be once|always|reject"
            )
        client = await self._get_client()
        if self._v2:
            path = f"{self._prefix}/session/{session_id}/permission/{permission_id}/reply"
        else:
            path = f"/permission/{permission_id}/reply"
        resp = await client.post(
            path,
            json={"requestID": permission_id, "directory": directory, "reply": response},
        )
        resp.raise_for_status()
        if not resp.content or not resp.content.strip():
            return {"ok": True}
        try:
            return self._unwrap(resp) or {"ok": True}
        except Exception:
            return {"ok": True}

    # ------------------------------------------------------------------
    # Questions (v1: OpenCode Question API — v2: Form API, adapted)
    # ------------------------------------------------------------------

    async def list_questions(self, session_id: str) -> List[Dict[str, Any]]:
        client = await self._get_client()
        if self._v2:
            resp = await client.get(f"{self._prefix}/session/{session_id}/form")
            resp.raise_for_status()
            return self._unwrap(resp) or []
        resp = await client.get("/question")
        resp.raise_for_status()
        if not resp.content or not resp.content.strip():
            return []
        all_questions = resp.json()
        if not isinstance(all_questions, list):
            return []
        return [q for q in all_questions if q.get("sessionID") == session_id]

    async def reply_to_question(
        self, session_id: str, question_id: str, answer: str
    ) -> bool:
        """Answer a pending question (v1) or form (v2).

        session_id is required for v2 (forms live under
        /session/{id}/form/{formID}) and ignored for v1 (questions are
        answered by a global id, no session scoping).
        """
        client = await self._get_client()
        if self._v2:
            # v2's Form generalizes to multiple typed fields; this shim only
            # answers a single-field form (matching v1's one-string-question
            # shape) by fetching the form to find its first field's key.
            form_resp = await client.get(
                f"{self._prefix}/session/{session_id}/form/{question_id}"
            )
            form_resp.raise_for_status()
            form = self._unwrap(form_resp)
            fields = (form or {}).get("fields") or []
            key = fields[0].get("key") if fields else "answer"
            resp = await client.post(
                f"{self._prefix}/session/{session_id}/form/{question_id}/reply",
                json={"answer": {key: answer}},
            )
        else:
            resp = await client.post(
                f"/question/{question_id}/reply",
                json={"answers": [[answer]]},
            )
        resp.raise_for_status()
        return True

    async def reject_question(self, session_id: str, question_id: str) -> bool:
        client = await self._get_client()
        if self._v2:
            # No direct "reject" verb in v2's Form API -- deleting the form
            # is the closest equivalent (DELETE /session/{id}/form/{formID}).
            resp = await client.delete(
                f"{self._prefix}/session/{session_id}/form/{question_id}"
            )
        else:
            resp = await client.post(f"/question/{question_id}/reject")
        resp.raise_for_status()
        return True

    # ------------------------------------------------------------------
    # SSE event stream
    # ------------------------------------------------------------------

    async def subscribe_events(
        self, session_id: str
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream permission and question/form events.

        v1: session-scoped SSE at /session/{id}/event.
        v2: SSE is global at /api/event (not session-scoped) -- filter
        client-side on the event payload's own session id field.
        Subscribe BEFORE calling send_message to avoid missing events.
        """
        _HITL_EVENTS = {"permission.asked", "question.asked", "form.created"}
        client = await self._get_client()
        path = f"{self._prefix}/event" if self._v2 else f"/session/{session_id}/event"
        async with client.stream("GET", path, timeout=None) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("OpenCode SSE: unparseable line: %r", raw)
                    continue
                if event.get("type") not in _HITL_EVENTS:
                    continue
                if self._v2:
                    props = event.get("properties", event)
                    if props.get("sessionID") not in (session_id, None):
                        continue
                yield event
