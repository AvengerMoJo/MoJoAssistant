"""
OAuth 2.1 Authorization Server state — in-memory with JSON persistence.
Tokens survive server restarts; expired tokens are filtered on load.
"""

import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, List
from threading import Lock

_log = logging.getLogger(__name__)


def _oauth_storage_dir() -> Path:
    memory_path = os.getenv("MEMORY_PATH", str(Path.home() / ".memory"))
    d = Path(memory_path) / "oauth"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class AuthorizationCodeData:
    """OAuth authorization code with PKCE support"""

    code: str
    client_id: Optional[str]
    redirect_uri: str
    scope: str
    code_challenge: str
    code_challenge_method: str  # "S256" or "plain"
    expires_at: datetime
    used: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self) -> bool:
        """Check if authorization code has expired"""
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self) -> bool:
        """Check if authorization code is valid (not used, not expired)"""
        return not self.used and not self.is_expired()


@dataclass
class AccessTokenData:
    """OAuth access token"""

    token: str
    client_id: Optional[str]
    scope: str
    expires_at: datetime
    refresh_token: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self) -> bool:
        """Check if access token has expired"""
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self) -> bool:
        """Check if access token is valid (not expired)"""
        return not self.is_expired()

    def get_expires_in(self) -> int:
        """Get remaining time until expiration in seconds"""
        if self.is_expired():
            return 0
        delta = self.expires_at - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))


@dataclass
class RefreshTokenData:
    """OAuth refresh token"""

    token: str
    client_id: Optional[str]
    scope: str
    expires_at: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self) -> bool:
        """Check if refresh token has expired"""
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self) -> bool:
        """Check if refresh token is valid (not expired)"""
        return not self.is_expired()


class AuthorizationCodeStore:
    """
    Thread-safe in-memory store for authorization codes
    Automatically cleans up expired codes
    """

    def __init__(self, cleanup_interval: int = 300):
        """
        Initialize authorization code store

        Args:
            cleanup_interval: Seconds between automatic cleanup (default: 300)
        """
        self._codes: Dict[str, AuthorizationCodeData] = {}
        self._lock = Lock()
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()

    def create(
        self,
        client_id: Optional[str],
        redirect_uri: str,
        scope: str,
        code_challenge: str,
        code_challenge_method: str,
        ttl: int = 600,
    ) -> AuthorizationCodeData:
        """
        Create new authorization code

        Args:
            client_id: Optional client identifier
            redirect_uri: Redirect URI for callback
            scope: Requested scopes
            code_challenge: PKCE code challenge
            code_challenge_method: PKCE method ("S256")
            ttl: Time to live in seconds (default: 600 = 10 minutes)

        Returns:
            Authorization code data
        """
        code = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)

        code_data = AuthorizationCodeData(
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            expires_at=expires_at,
        )

        with self._lock:
            self._codes[code] = code_data
            self._maybe_cleanup()

        return code_data

    def get(self, code: str) -> Optional[AuthorizationCodeData]:
        """
        Get authorization code data

        Args:
            code: Authorization code

        Returns:
            Authorization code data if found, None otherwise
        """
        with self._lock:
            return self._codes.get(code)

    def mark_used(self, code: str) -> bool:
        """
        Mark authorization code as used (one-time use)

        Args:
            code: Authorization code

        Returns:
            True if marked successfully, False if code not found
        """
        with self._lock:
            code_data = self._codes.get(code)
            if code_data:
                code_data.used = True
                return True
            return False

    def delete(self, code: str) -> bool:
        """
        Delete authorization code

        Args:
            code: Authorization code

        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            if code in self._codes:
                del self._codes[code]
                return True
            return False

    def _maybe_cleanup(self):
        """Clean up expired codes if interval has passed"""
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup()
            self._last_cleanup = now

    def _cleanup(self):
        """Remove expired or used codes"""
        expired_codes = [
            code for code, data in self._codes.items() if not data.is_valid()
        ]
        for code in expired_codes:
            del self._codes[code]

    def count(self) -> int:
        """Get number of stored codes"""
        with self._lock:
            return len(self._codes)


class TokenStore:
    """
    Thread-safe store for access and refresh tokens with JSON persistence.
    Tokens survive server restarts; expired tokens are dropped on load.
    """

    def __init__(self, cleanup_interval: int = 300):
        self._access_tokens: Dict[str, AccessTokenData] = {}
        self._refresh_tokens: Dict[str, RefreshTokenData] = {}
        self._lock = Lock()
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()
        self._path = _oauth_storage_dir() / "tokens.json"
        self._load()

    def _load(self):
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            now = datetime.now(timezone.utc)
            for token, td in raw.get("access_tokens", {}).items():
                expires_at = datetime.fromisoformat(td["expires_at"])
                if expires_at > now:
                    self._access_tokens[token] = AccessTokenData(
                        token=td["token"],
                        client_id=td.get("client_id"),
                        scope=td["scope"],
                        expires_at=expires_at,
                        refresh_token=td.get("refresh_token"),
                        created_at=datetime.fromisoformat(td["created_at"]),
                    )
            for token, rd in raw.get("refresh_tokens", {}).items():
                expires_at = datetime.fromisoformat(rd["expires_at"])
                if expires_at > now:
                    self._refresh_tokens[token] = RefreshTokenData(
                        token=rd["token"],
                        client_id=rd.get("client_id"),
                        scope=rd["scope"],
                        expires_at=expires_at,
                        created_at=datetime.fromisoformat(rd["created_at"]),
                    )
            _log.info(
                "OAuth token store loaded: %d access, %d refresh tokens",
                len(self._access_tokens),
                len(self._refresh_tokens),
            )
        except Exception as e:
            _log.warning("Failed to load OAuth token store from %s: %s", self._path, e)

    def _save(self):
        try:
            data = {
                "access_tokens": {
                    t: {
                        "token": td.token,
                        "client_id": td.client_id,
                        "scope": td.scope,
                        "expires_at": td.expires_at.isoformat(),
                        "refresh_token": td.refresh_token,
                        "created_at": td.created_at.isoformat(),
                    }
                    for t, td in self._access_tokens.items()
                    if td.is_valid()
                },
                "refresh_tokens": {
                    t: {
                        "token": rd.token,
                        "client_id": rd.client_id,
                        "scope": rd.scope,
                        "expires_at": rd.expires_at.isoformat(),
                        "created_at": rd.created_at.isoformat(),
                    }
                    for t, rd in self._refresh_tokens.items()
                    if rd.is_valid()
                },
            }
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(self._path)
        except Exception as e:
            _log.warning("Failed to persist OAuth token store: %s", e)

    def create_access_token(
        self,
        client_id: Optional[str],
        scope: str,
        ttl: int = 3600,
        create_refresh_token: bool = True,
        refresh_token_ttl: int = 2592000,
    ) -> AccessTokenData:
        """
        Create new access token (and optionally refresh token)

        Args:
            client_id: Optional client identifier
            scope: Granted scopes
            ttl: Access token time to live in seconds (default: 3600 = 1 hour)
            create_refresh_token: Whether to create refresh token (default: True)
            refresh_token_ttl: Refresh token TTL in seconds (default: 2592000 = 30 days)

        Returns:
            Access token data
        """
        access_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)

        refresh_token = None
        if create_refresh_token:
            refresh_token = secrets.token_urlsafe(32)
            refresh_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=refresh_token_ttl
            )

            refresh_data = RefreshTokenData(
                token=refresh_token,
                client_id=client_id,
                scope=scope,
                expires_at=refresh_expires_at,
            )

            with self._lock:
                self._refresh_tokens[refresh_token] = refresh_data

        token_data = AccessTokenData(
            token=access_token,
            client_id=client_id,
            scope=scope,
            expires_at=expires_at,
            refresh_token=refresh_token,
        )

        with self._lock:
            self._access_tokens[access_token] = token_data
            self._maybe_cleanup()

        self._save()
        return token_data

    def get_access_token(self, token: str) -> Optional[AccessTokenData]:
        """
        Get access token data

        Args:
            token: Access token

        Returns:
            Access token data if found and valid, None otherwise
        """
        with self._lock:
            token_data = self._access_tokens.get(token)
            if token_data and token_data.is_valid():
                return token_data
            return None

    def get_refresh_token(self, token: str) -> Optional[RefreshTokenData]:
        """
        Get refresh token data

        Args:
            token: Refresh token

        Returns:
            Refresh token data if found and valid, None otherwise
        """
        with self._lock:
            token_data = self._refresh_tokens.get(token)
            if token_data and token_data.is_valid():
                return token_data
            return None

    def revoke_access_token(self, token: str) -> bool:
        """
        Revoke access token

        Args:
            token: Access token

        Returns:
            True if revoked, False if not found
        """
        with self._lock:
            if token in self._access_tokens:
                del self._access_tokens[token]
                self._save()
                return True
            return False

    def revoke_refresh_token(self, token: str) -> bool:
        """
        Revoke refresh token

        Args:
            token: Refresh token

        Returns:
            True if revoked, False if not found
        """
        with self._lock:
            if token in self._refresh_tokens:
                del self._refresh_tokens[token]
                self._save()
                return True
            return False

    def _maybe_cleanup(self):
        """Clean up expired tokens if interval has passed"""
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup()
            self._last_cleanup = now

    def _cleanup(self):
        """Remove expired tokens and sync to disk."""
        expired_access = [
            token for token, data in self._access_tokens.items() if not data.is_valid()
        ]
        for token in expired_access:
            del self._access_tokens[token]

        expired_refresh = [
            token for token, data in self._refresh_tokens.items() if not data.is_valid()
        ]
        for token in expired_refresh:
            del self._refresh_tokens[token]

        if expired_access or expired_refresh:
            self._save()

    def count_access_tokens(self) -> int:
        """Get number of stored access tokens"""
        with self._lock:
            return len(self._access_tokens)

    def count_refresh_tokens(self) -> int:
        """Get number of stored refresh tokens"""
        with self._lock:
            return len(self._refresh_tokens)


@dataclass
class ClientRegistration:
    """OAuth client registration data"""

    client_id: str
    client_name: str
    redirect_uris: List[str]
    grant_types: List[str]
    response_types: List[str]
    scope: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ClientRegistrationStore:
    """
    Thread-safe store for OAuth client registrations with JSON persistence.
    Client IDs (like Claude Code's) survive server restarts.
    """

    def __init__(self):
        self._clients: Dict[str, ClientRegistration] = {}
        self._lock = Lock()
        self._path = _oauth_storage_dir() / "clients.json"
        self._load()

    def _load(self):
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            for cid, cd in raw.items():
                self._clients[cid] = ClientRegistration(
                    client_id=cd["client_id"],
                    client_name=cd["client_name"],
                    redirect_uris=cd["redirect_uris"],
                    grant_types=cd["grant_types"],
                    response_types=cd["response_types"],
                    scope=cd["scope"],
                    created_at=datetime.fromisoformat(cd["created_at"]),
                )
            _log.info("OAuth client store loaded: %d clients", len(self._clients))
        except Exception as e:
            _log.warning("Failed to load OAuth client store from %s: %s", self._path, e)

    def _save(self):
        try:
            data = {
                cid: {
                    "client_id": c.client_id,
                    "client_name": c.client_name,
                    "redirect_uris": c.redirect_uris,
                    "grant_types": c.grant_types,
                    "response_types": c.response_types,
                    "scope": c.scope,
                    "created_at": c.created_at.isoformat(),
                }
                for cid, c in self._clients.items()
            }
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(self._path)
        except Exception as e:
            _log.warning("Failed to persist OAuth client store: %s", e)

    def register_client(
        self,
        client_name: str,
        redirect_uris: List[str],
        grant_types: List[str],
        response_types: List[str],
        scope: str = "",
    ) -> ClientRegistration:
        client_id = secrets.token_urlsafe(16)

        client = ClientRegistration(
            client_id=client_id,
            client_name=client_name,
            redirect_uris=redirect_uris,
            grant_types=grant_types,
            response_types=response_types,
            scope=scope,
        )

        with self._lock:
            self._clients[client_id] = client

        self._save()
        return client

    def get_client(self, client_id: str) -> Optional[ClientRegistration]:
        """Get client by ID"""
        with self._lock:
            return self._clients.get(client_id)

    def delete_client(self, client_id: str) -> bool:
        """Delete client registration"""
        with self._lock:
            if client_id in self._clients:
                del self._clients[client_id]
                self._save()
                return True
            return False


# Global singleton instances
_authorization_code_store: Optional[AuthorizationCodeStore] = None
_token_store: Optional[TokenStore] = None
_client_registration_store: Optional[ClientRegistrationStore] = None


def get_authorization_code_store() -> AuthorizationCodeStore:
    """Get global authorization code store instance"""
    global _authorization_code_store
    if _authorization_code_store is None:
        _authorization_code_store = AuthorizationCodeStore()
    return _authorization_code_store


def get_token_store() -> TokenStore:
    """Get global token store instance"""
    global _token_store
    if _token_store is None:
        _token_store = TokenStore()
    return _token_store


def get_client_registration_store() -> ClientRegistrationStore:
    """Get global client registration store instance"""
    global _client_registration_store
    if _client_registration_store is None:
        _client_registration_store = ClientRegistrationStore()
    return _client_registration_store
