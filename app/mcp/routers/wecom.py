"""WeCom (企业微信) callback webhook.

Routes:
  GET  /api/wecom/callback  — one-time URL verification handshake
  POST /api/wecom/callback  — inbound message delivery (encrypted XML body)

Delegates all signature/crypto work to the live WeComMessengerAdapter
instance (held by the shared MessengerManager) so there's exactly one
place — wecom_crypto.py — that knows the algorithm.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request, Response

from app.mcp.adapters.messenger.wecom_crypto import WeComCryptoError

logger = logging.getLogger("mojo_assistant.messenger.wecom.router")

router = APIRouter(prefix="/api/wecom")


def _find_adapter() -> Optional["object"]:
    from app.mcp.adapters.messenger.manager import get_shared_manager

    for adapter in get_shared_manager().adapters:
        if getattr(adapter, "adapter_type", "") == "wecom":
            return adapter
    return None


@router.get("/callback")
async def verify_callback_url(
    msg_signature: str = "", timestamp: str = "", nonce: str = "", echostr: str = ""
):
    adapter = _find_adapter()
    if adapter is None:
        return Response(content="wecom adapter not configured", status_code=503)
    try:
        plaintext = adapter.verify_url(msg_signature, timestamp, nonce, echostr)
    except WeComCryptoError as exc:
        logger.warning("[wecom/router] URL verification failed: %s", exc)
        return Response(content="invalid signature", status_code=403)
    return Response(content=plaintext, media_type="text/plain")


@router.post("/callback")
async def receive_callback(
    request: Request, msg_signature: str = "", timestamp: str = "", nonce: str = ""
):
    adapter = _find_adapter()
    if adapter is None:
        return Response(content="wecom adapter not configured", status_code=503)
    body = await request.body()
    adapter.handle_callback(msg_signature, timestamp, nonce, body.decode("utf-8", errors="replace"))
    # WeCom only requires a 200 response; replies go out async via message/send.
    return Response(content="success", media_type="text/plain")
