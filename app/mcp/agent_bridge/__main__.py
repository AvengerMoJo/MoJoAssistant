"""Entry point: python -m app.mcp.agent_bridge.server"""

from __future__ import annotations

import argparse
import logging
import secrets
import sys

import uvicorn

from app.mcp.agent_bridge.config import load_config
from app.mcp.agent_bridge.server import _ensure


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent bridge MCP server (Streamable HTTP)")
    parser.add_argument("--host", default=None, help="Bind address (default: from config)")
    parser.add_argument("--port", type=int, default=None, help="Port (default: 8497)")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    cfg = load_config()

    host = args.host or cfg.get("bind", "0.0.0.0")
    port = args.port or cfg.get("port", 8497)

    # Ensure bridge has a password (auto-generate if empty)
    if not cfg.get("password"):
        pw = secrets.token_hex(16)
        cfg["password"] = pw
        print(f"[agent-bridge] Auto-generated bridge password: {pw}", file=sys.stderr)
        print(
            "[agent-bridge] Persist in ~/.memory/config/agent_bridge.json password field "
            "to keep across restarts.",
            file=sys.stderr,
        )

    _ensure()
    app = _ensure()[0].streamable_http_app()

    # Apply BasicAuth middleware with the bridge password
    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    import base64

    class BasicAuthMiddleware(BaseHTTPMiddleware):
        def __init__(self, app, password: str):
            super().__init__(app)
            self._expected = base64.b64encode(f"opencode:{password}".encode()).decode()

        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
            auth = request.headers.get("authorization", "")
            if auth == f"Basic {self._expected}":
                return await call_next(request)
            return PlainTextResponse("Unauthorized", status_code=401)

    app.add_middleware(BasicAuthMiddleware, password=cfg["password"])

    print(f"[agent-bridge] Listening on http://{host}:{port}/mcp", file=sys.stderr)
    print(f"[agent-bridge] MCP password: {cfg['password']}", file=sys.stderr)
    uvicorn.run(app, host=host, port=port, log_level=args.log_level)


if __name__ == "__main__":
    main()
