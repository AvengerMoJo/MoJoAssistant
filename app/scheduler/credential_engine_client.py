"""Synchronous client for the credential engine's web API (ai-credential-manager /api/v1).

The resource pool is synchronous code that runs inside event loops, so it cannot use the MCP client in
credential_manager_client.py (asyncio.run inside a running loop). This one speaks plain HTTP to the same
functions, with the same OAuth grants and the same owner-set policy.

What it gives the pool, per resource that opted in (`credential_engine: true` in resource_pool.json):
  - the key, fetched when first needed and again shortly before the lease expires. It lives in memory only,
    is never written to config or env, and every fetch is a lease the owner can read in the service.
  - the outcome of calls, reported so the engine's breaker / quota / probe state stays shared.

No fallback: if the engine cannot hand over a key, reading the key raises CredentialEngineError. The pool
does not quietly use a stale or environment-variable key instead.
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

import httpx

BOOTSTRAP_PATH = Path(os.path.expanduser("~/.memory/config/ai_credential_manager_client.json"))
REFRESH_MARGIN_S = 60
# A provider refusing the key we hold: the key may have been rotated or revoked, so stop reusing it.
_AUTH_REFUSED = re.compile(r"\b(401|403)\b|unauthori[sz]ed|forbidden|invalid[ _-]?api[ _-]?key|incorrect api key|authentication", re.I)
_log = logging.getLogger("credential_engine")


class CredentialEngineError(RuntimeError):
    """The engine could not supply what was asked. Never swallowed into a fallback."""


@dataclass
class _Held:
    api_key: Optional[str]
    lease_id: str
    expires_at: float


class CredentialEngineClient:
    def __init__(self, bootstrap_path: Path = BOOTSTRAP_PATH, transport: Optional[httpx.BaseTransport] = None):
        if not bootstrap_path.exists():
            raise CredentialEngineError(f"credential engine bootstrap config not found at {bootstrap_path}")
        b = json.loads(bootstrap_path.read_text())
        c = b["mojoassistant_client"]
        # Local loopback first: every LLM call's key must not make a round trip through the public internet.
        self._url = (b.get("service_url_local") or b["service_url"]).rstrip("/")
        self._tenant = b.get("tenant_id") or c.get("tenant_id")
        if not self._tenant:
            raise CredentialEngineError("bootstrap config has no tenant_id; the engine scopes are per tenant")
        self._client_id, self._secret, self._redirect = c["client_id"], c["client_secret"], c["redirect_uri"]
        self._http = httpx.Client(base_url=self._url, timeout=15.0, transport=transport)
        self._lock = threading.RLock()
        self._tokens: Dict[str, tuple] = {}
        self._held: Dict[str, _Held] = {}
        self._leases: Dict[str, str] = {}  # resource id -> latest lease id, for reporting

    # ── auth ───────────────────────────────────────────────────────────────────────────────
    def _token(self, scope: str) -> str:
        with self._lock:
            cached = self._tokens.get(scope)
            if cached and cached[1] - REFRESH_MARGIN_S > time.time():
                return cached[0]
            verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            try:
                r = self._http.post("/oauth/authorize", data={
                    "action": "allow", "client_id": self._client_id, "redirect_uri": self._redirect, "scope": scope,
                    "state": secrets.token_urlsafe(8), "code_challenge": challenge, "code_challenge_method": "S256"})
                loc = r.headers.get("location", "")
                if r.status_code not in (302, 303) or "code=" not in loc:
                    raise CredentialEngineError(f"scope {scope!r} was not issued to this client: {r.status_code} {loc or r.text}")
                code = loc.split("code=")[1].split("&")[0]
                r = self._http.post("/oauth/token", data={
                    "grant_type": "authorization_code", "code": code, "redirect_uri": self._redirect,
                    "code_verifier": verifier, "client_id": self._client_id, "client_secret": self._secret})
            except httpx.RequestError as e:
                raise CredentialEngineError(f"credential engine unreachable at {self._url}: {e}") from e
            if r.status_code != 200:
                raise CredentialEngineError(f"token exchange failed: {r.status_code} {r.text}")
            body = r.json()
            self._tokens[scope] = (body["access_token"], time.time() + body.get("expires_in", 3600))
            return body["access_token"]

    def _post(self, path: str, scope: str, payload: dict) -> dict:
        try:
            r = self._http.post(f"/api/v1/{path}", json=payload, headers={"Authorization": f"Bearer {self._token(scope)}"})
        except httpx.RequestError as e:
            raise CredentialEngineError(f"credential engine unreachable at {self._url}: {e}") from e
        body = r.json() if r.content else {}
        if r.status_code != 200:
            raise CredentialEngineError(f"{path} refused ({r.status_code}): {body.get('error', r.text)}")
        return body

    # ── what the pool uses ─────────────────────────────────────────────────────────────────
    def api_key(self, resource_id: str) -> Optional[str]:
        """The key for one resource, from a live lease (renewed shortly before it expires)."""
        with self._lock:
            held = self._held.get(resource_id)
            if held and held.expires_at - REFRESH_MARGIN_S > time.time():
                return held.api_key
            got = self._post("acquire", f"tenant:{self._tenant}:acquire", {"resource_id": resource_id})
            self._held[resource_id] = _Held(got.get("api_key"), got["lease_id"], got["expires_at"])
            self._leases[resource_id] = got["lease_id"]
            return got.get("api_key")

    def key_source(self, resource_id: str) -> Callable[[], Optional[str]]:
        return lambda: self.api_key(resource_id)

    def report(self, resource_id: str, success: bool, error_message: Optional[str] = None) -> None:
        """Tell the engine how a call went. Runs off the calling thread: reporting must not slow or break a
        model call, but a failed report is logged as an error, not dropped."""
        with self._lock:
            lease = self._leases.get(resource_id)
            if not success and error_message and _AUTH_REFUSED.search(error_message) and resource_id in self._held:
                # Drop the held key: the next call asks the engine again and gets whatever the vault holds now
                # (a rotated key), instead of replaying a refused one until the lease runs out.
                del self._held[resource_id]
        if lease is None:
            return  # no key was ever fetched for this resource in this process, so there is no lease to report on

        def send():
            try:
                self._post("report", f"tenant:{self._tenant}:acquire",
                           {"lease_id": lease, "success": success, "error_message": error_message})
            except Exception as e:
                _log.error("could not report usage of %s to the credential engine: %s", resource_id, e)

        threading.Thread(target=send, name="credential-engine-report", daemon=True).start()


_client: Optional[CredentialEngineClient] = None
_client_lock = threading.Lock()


def get_credential_engine_client() -> CredentialEngineClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = CredentialEngineClient()
        return _client


def reset_credential_engine_client() -> None:
    global _client
    with _client_lock:
        _client = None
