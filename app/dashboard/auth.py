"""
Dashboard authentication — simple HMAC-signed session cookie.
Password is set via DASHBOARD_PASSWORD env var (falls back to MCP_API_KEY).
"""

import hashlib
import hmac
import os
import base64

COOKIE_NAME = "mojo_dash"
_SECRET: str | None = None


def _secret() -> str:
    global _SECRET
    if _SECRET is None:
        _SECRET = os.environ.get("DASHBOARD_PASSWORD") or os.environ.get("MCP_API_KEY") or "changeme"
    return _SECRET


def make_token() -> str:
    """Return a signed session token."""
    msg = b"authenticated"
    sig = hmac.new(_secret().encode(), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode()


def verify_token(token: str | None) -> bool:
    """Return True if the cookie token is valid."""
    if not token:
        return False
    try:
        expected = make_token()
        return hmac.compare_digest(token, expected)
    except Exception:
        return False


def check_password(password: str) -> bool:
    """Return True if the submitted password matches."""
    return hmac.compare_digest(password, _secret())
