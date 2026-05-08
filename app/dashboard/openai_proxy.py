"""
OpenAI-Compatible Proxy — /v1/models and /v1/chat/completions.

Allows any OpenAI-compatible client (OpenWebUI, Cursor, etc.) to talk
to MoJoAssistant roles directly using the standard OpenAI API format.

Routes:
  GET  /v1/models           — list available roles as models
  POST /v1/chat/completions — send chat message to a role

Authentication:
  Bearer token in Authorization header, validated against
  ~/.memory/config/openai_proxy.json (key: "api_key").
  Auto-generated on first startup if not present.
"""
# [mojo-integration]

from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, Security
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config.paths import get_memory_subpath
from app.roles.role_manager import RoleManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")
security = HTTPBearer(auto_error=False)

# Module-level cache for RoleManager with TTL
_role_manager_cache: Optional[Tuple[float, RoleManager]] = None
_ROLE_MANAGER_TTL = 60  # seconds


def _load_proxy_config() -> Dict[str, Any]:
    """Load proxy config from ~/.memory/config/openai_proxy.json."""
    config_path = Path(get_memory_subpath("config")) / "openai_proxy.json"
    if not config_path.exists():
        # Generate a default API key on first run
        api_key = secrets.token_urlsafe(32)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps({"api_key": api_key}, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info(f"Generated OpenAI proxy API key: {api_key}")
        return {"api_key": api_key}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


async def _verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> str:
    """Verify Bearer token against proxy config. Returns the token on success."""
    config = _load_proxy_config()
    expected = config.get("api_key")

    # If no key configured, allow access (first run)
    if not expected:
        return ""

    if not credentials or credentials.credentials != expected:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid or missing API key",
                    "type": "authentication_error",
                }
            },
        )
    return credentials.credentials


def _get_role_manager() -> RoleManager:
    """Get cached RoleManager instance (TTL: 60s)."""
    global _role_manager_cache
    now = time.time()
    if _role_manager_cache is None or now - _role_manager_cache[0] > _ROLE_MANAGER_TTL:
        _role_manager_cache = (now, RoleManager())
    return _role_manager_cache[1]


@router.get("/models")
async def list_models(token: str = Security(_verify_token)):
    """List available roles as OpenAI-compatible models.

    Requires: Bearer token in Authorization header.

    Returns:
        OpenAI-compatible model list response.
    """
    manager = _get_role_manager()
    roles = manager.list_roles()

    models = []
    for role in roles:
        role_id = role.get("id", "unknown")
        name = role.get("name", role_id)
        models.append({
            "id": role_id,
            "object": "model",
            "created": 1700000000,
            "owned_by": "mojoassistant",
            "permission": [],
            "root": role_id,
            "parent": None,
            "capabilities": role.get("capabilities", []),
            "description": role.get("purpose", "")[:200],
        })

    return JSONResponse({
        "object": "list",
        "data": models,
    })


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    token: str = Security(_verify_token),
):
    """OpenAI-compatible chat completion endpoint.

    Requires: Bearer token in Authorization header.

    Accepts:
        {
            "model": "researcher",  // role_id
            "messages": [{"role": "user", "content": "..."}],
            "stream": false,
            "temperature": 0.7,
            "max_tokens": 1000
        }

    Returns:
        OpenAI-compatible chat completion response.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}},
            status_code=400,
        )

    model = body.get("model", "")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    temperature = body.get("temperature", 0.7)
    max_tokens = body.get("max_tokens", 1000)

    if not model:
        return JSONResponse(
            {"error": {"message": "model (role_id) is required", "type": "invalid_request_error"}},
            status_code=400,
        )

    if not messages:
        return JSONResponse(
            {"error": {"message": "messages array is required", "type": "invalid_request_error"}},
            status_code=400,
        )

    # Streaming not yet supported — fail fast with clear message
    if stream:
        return JSONResponse(
            {"error": {
                "message": "Streaming not yet supported. Set stream=false or omit.",
                "type": "not_implemented_error",
            }},
            status_code=501,
        )

    # Load role
    manager = _get_role_manager()
    role = manager.get(model)
    if not role:
        return JSONResponse(
            {"error": {"message": f"Role '{model}' not found", "type": "not_found_error"}},
            status_code=404,
        )

    # Build context from messages
    user_message = ""
    conversation_history = []
    for msg in messages:
        role_type = msg.get("role", "user")
        content = msg.get("content", "")
        if role_type == "user":
            user_message = content
        conversation_history.append({"role": role_type, "content": content})

    # Use role_chat for the actual response
    try:
        from app.scheduler.role_chat import RoleChatSession

        session = RoleChatSession(role_id=model)
        response = await session.chat(user_message)

        response_text = response.get("response", "")
        session_id = response.get("session_id", "")

        if stream:
            return StreamingResponse(
                _stream_response(response_text, model, session_id),
                media_type="text/event-stream",
            )

        return JSONResponse({
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text,
                },
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "session_id": session_id,
        })

    except Exception as e:
        return JSONResponse(
            {"error": {"message": f"Chat error: {e}", "type": "server_error"}},
            status_code=500,
        )


async def _stream_response(text: str, model: str, session_id: str):
    """Generate SSE stream for chat response."""
    chunk_size = 20
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        data = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {"content": chunk},
                "finish_reason": None,
            }],
        }
        yield f"data: {json.dumps(data)}\n\n"

    # Final chunk
    data = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop",
        }],
    }
    yield f"data: {json.dumps(data)}\n\n"
    yield "data: [DONE]\n\n"
