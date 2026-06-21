"""
OpenCode HTTP client — direct httpx calls to OpenCode's REST API.

Replaces coding-agent-mcp-tool's OpenCodeBackend. Works with OpenCode running
inside a CubeSandbox VM (via proxy URL) or directly on the host.

API surface (all under base_url with BasicAuth):
  POST /session                              → create session
  GET  /session                              → list sessions
  GET  /session/{id}                         → get session
  DELETE /session/{id}                       → delete session
  POST /session/{id}/message                 → send message (blocking, 300s)
  GET  /session/{id}/message                 → get messages
  GET  /permission                           → list pending permissions
  POST /permission/{id}/reply                → respond to permission
  GET  /question                             → list pending questions
  POST /question/{id}/reply                  → answer question
  POST /question/{id}/reject                 → reject question
  GET  /session/{id}/event                   → SSE stream (permissions + questions)
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

MESSAGE_TIMEOUT = 300.0
DEFAULT_TIMEOUT = 30.0


class OpenCodeClient:
    """Async HTTP client for OpenCode server.

    Args:
        base_url: OpenCode server URL (e.g. http://localhost:4173 or CubeSandbox proxy)
        password: Basic auth password (username is always "opencode")
    """

    def __init__(
        self,
        base_url: str,
        password: Optional[str] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = httpx.BasicAuth("opencode", password or "")
        self._client: Optional[httpx.AsyncClient] = None

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
        resp = await client.post("/session", json=kwargs or None)
        resp.raise_for_status()
        return resp.json()

    async def list_sessions(self) -> List[Dict[str, Any]]:
        client = await self._get_client()
        resp = await client.get("/session")
        resp.raise_for_status()
        return resp.json()

    async def get_session(self, session_id: str) -> Dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(f"/session/{session_id}")
        resp.raise_for_status()
        return resp.json()

    async def delete_session(self, session_id: str) -> Dict[str, Any]:
        client = await self._get_client()
        resp = await client.delete(f"/session/{session_id}")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_message(
        self, session_id: str, content: str, **kwargs: Any
    ) -> Dict[str, Any]:
        client = await self._get_client()
        payload: Dict[str, Any] = {
            "parts": [{"type": "text", "text": content}],
            **kwargs,
        }
        resp = await client.post(
            f"/session/{session_id}/message",
            json=payload,
            timeout=MESSAGE_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        client = await self._get_client()
        resp = await client.get(f"/session/{session_id}/message")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    async def list_permissions(self, session_id: str) -> List[Dict[str, Any]]:
        client = await self._get_client()
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
        resp = await client.post(
            f"/permission/{permission_id}/reply",
            json={
                "requestID": permission_id,
                "directory": directory,
                "reply": response,
            },
        )
        resp.raise_for_status()
        if not resp.content or not resp.content.strip():
            return {"ok": True}
        try:
            return resp.json()
        except Exception:
            return {"ok": True}

    # ------------------------------------------------------------------
    # Questions (OpenCode Question API)
    # ------------------------------------------------------------------

    async def list_questions(self, session_id: str) -> List[Dict[str, Any]]:
        client = await self._get_client()
        resp = await client.get("/question")
        resp.raise_for_status()
        if not resp.content or not resp.content.strip():
            return []
        all_questions = resp.json()
        if not isinstance(all_questions, list):
            return []
        return [q for q in all_questions if q.get("sessionID") == session_id]

    async def reply_to_question(self, question_id: str, answer: str) -> bool:
        client = await self._get_client()
        resp = await client.post(
            f"/question/{question_id}/reply",
            json={"answers": [[answer]]},
        )
        resp.raise_for_status()
        return True

    async def reject_question(self, question_id: str) -> bool:
        client = await self._get_client()
        resp = await client.post(f"/question/{question_id}/reject")
        resp.raise_for_status()
        return True

    # ------------------------------------------------------------------
    # SSE event stream
    # ------------------------------------------------------------------

    async def subscribe_events(
        self, session_id: str
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream permission and question events from SSE /session/{id}/event.

        Yields dicts for both 'permission.asked' and 'question.asked' events.
        Subscribe BEFORE calling send_message to avoid missing events.
        """
        _HITL_EVENTS = {"permission.asked", "question.asked"}
        client = await self._get_client()
        async with client.stream(
            "GET", f"/session/{session_id}/event", timeout=None
        ) as resp:
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
                if event.get("type") in _HITL_EVENTS:
                    yield event
