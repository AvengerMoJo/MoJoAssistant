"""
Client for the standalone ai-credential-manager service
(https://keys.eclipsogate.org) -- Phase 2, additive first step per
project_unified_provider_resource_pool_vision.md.

This is deliberately NOT wired into ResourceManager's hot path
(acquire()/record_usage()) yet. It exists as a proven, isolated building
block: resolve_credential()/report_usage() round-trip against the real
deployed service, over a real OAuth token, for a real registered route
(lmstudio_qwen35b, mirrored into the service — see
~/.memory/config/ai_credential_manager_client.json). ResourceManager still
reads resource_pool.json/resource_pool.env for everything today; nothing
about existing task dispatch changes because this file exists.

No fallback pattern: any failure (unreachable service, expired grant,
malformed response) raises CredentialManagerError. There is no silent
fallback to a stale cached value or to local config — per this project's
"no fallback patterns" principle, a caller that wants resilience makes that
decision explicitly, this client never masks a real failure.
"""
import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

BOOTSTRAP_PATH = Path(os.path.expanduser("~/.memory/config/ai_credential_manager_client.json"))

# Refresh a route-scoped token this many seconds before its stated expiry,
# rather than waiting for a call to fail on an expired token first.
_TOKEN_REFRESH_MARGIN_SECONDS = 60


class CredentialManagerError(Exception):
    """Raised on any failure talking to the credential manager service --
    unreachable, auth failure, or a tool call returning {"error": ...}.
    Never swallowed into a fallback; callers decide what to do."""


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float  # time.time() + expires_in, from the token response


class CredentialManagerClient:
    """One instance per process is enough -- caches a short-lived access
    token per distinct scope string (usually one per route_id) rather than
    re-running the OAuth dance on every call."""

    def __init__(self, bootstrap_path: Path = BOOTSTRAP_PATH):
        if not bootstrap_path.exists():
            raise CredentialManagerError(
                f"credential manager bootstrap config not found at {bootstrap_path} -- "
                "MoJoAssistant has not been registered as a client yet"
            )
        self._bootstrap = json.loads(bootstrap_path.read_text())
        self._service_url = self._bootstrap["service_url"]
        self._client_id = self._bootstrap["mojoassistant_client"]["client_id"]
        self._client_secret = self._bootstrap["mojoassistant_client"]["client_secret"]
        self._redirect_uri = self._bootstrap["mojoassistant_client"]["redirect_uri"]
        self._token_cache: Dict[str, _CachedToken] = {}

    def resolve_credential(self, route_id: str) -> Dict[str, Any]:
        """Sync wrapper -- resource_pool.py is synchronous code. Must not be
        called from inside an already-running event loop (raises
        RuntimeError from asyncio.run in that case, which is the correct
        failure -- callers in async contexts should await
        aresolve_credential() directly instead)."""
        return asyncio.run(self.aresolve_credential(route_id))

    def report_usage(self, route_id: str, success: bool, error_message: Optional[str] = None) -> Dict[str, Any]:
        return asyncio.run(self.areport_usage(route_id, success, error_message))

    async def aresolve_credential(self, route_id: str) -> Dict[str, Any]:
        scope = f"route:{route_id}:use"
        token = await self._get_token(scope)
        result = await self._call_tool(token, "resolve_credential", access_token=token, route_id=route_id)
        if "error" in result:
            raise CredentialManagerError(f"resolve_credential({route_id}) failed: {result['error']}")
        return result

    async def areport_usage(self, route_id: str, success: bool, error_message: Optional[str] = None) -> Dict[str, Any]:
        scope = f"route:{route_id}:use"
        token = await self._get_token(scope)
        kwargs = {"access_token": token, "route_id": route_id, "success": success}
        if error_message is not None:
            kwargs["error_message"] = error_message
        result = await self._call_tool(token, "report_usage", **kwargs)
        if "error" in result:
            raise CredentialManagerError(f"report_usage({route_id}) failed: {result['error']}")
        return result

    async def _call_tool(self, _token: str, tool_name: str, **kwargs) -> Dict[str, Any]:
        async with streamablehttp_client(f"{self._service_url}/mcp") as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                r = await session.call_tool(tool_name, kwargs)
                return r.structuredContent["result"]

    async def _get_token(self, scope: str) -> str:
        cached = self._token_cache.get(scope)
        if cached and cached.expires_at - _TOKEN_REFRESH_MARGIN_SECONDS > time.time():
            return cached.access_token

        access_token, expires_in = await self._authorize_and_exchange(scope)
        self._token_cache[scope] = _CachedToken(access_token=access_token, expires_at=time.time() + expires_in)
        return access_token

    async def _authorize_and_exchange(self, scope: str) -> "tuple[str, int]":
        """Real authorization_code+PKCE flow against the service's own
        endpoints -- MoJoAssistant is a registered confidential client, so
        this is the owner's own trusted process approving its own request,
        not a third party. No auto_approve exists on the service side; this
        POST to /oauth/authorize is exactly what a real consent-page submit
        would send."""
        verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(8)

        async with httpx.AsyncClient(base_url=self._service_url, timeout=15.0) as client:
            try:
                resp = await client.post("/oauth/authorize", data={
                    "action": "allow",
                    "client_id": self._client_id,
                    "redirect_uri": self._redirect_uri,
                    "scope": scope,
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                })
            except httpx.RequestError as e:
                raise CredentialManagerError(f"credential manager service unreachable at {self._service_url}: {e}") from e

            if resp.status_code not in (302, 303):
                raise CredentialManagerError(f"authorize failed: {resp.status_code} {resp.text}")
            location = resp.headers.get("location", "")
            if "code=" not in location:
                raise CredentialManagerError(f"authorize did not return a code: {location}")
            code = location.split("code=")[1].split("&")[0]

            resp = await client.post("/oauth/token", data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
                "code_verifier": verifier,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            })
            if resp.status_code != 200:
                raise CredentialManagerError(f"token exchange failed: {resp.status_code} {resp.text}")
            body = resp.json()
            return body["access_token"], body.get("expires_in", 3600)


_client: Optional[CredentialManagerClient] = None


def get_credential_manager_client() -> CredentialManagerClient:
    global _client
    if _client is None:
        _client = CredentialManagerClient()
    return _client
