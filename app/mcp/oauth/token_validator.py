"""
OAuth 2.1 JWT Token Validator
Handles token validation for Claude Connectors compliance
"""
import time
import json
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import jwt
from jwt import PyJWKClient, PyJWKClientError
import httpx
from ..core.models import ErrorCode
from .models import OAuthToken, OAuthError
from app.config.app_config import OAuthConfig
from app.config.logging_config import get_logger


class TokenValidationError(Exception):
    """Token validation specific errors"""
    def __init__(self, message: str, error_code: str = "invalid_token"):
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class TokenValidator:
    """OAuth 2.1 JWT Token Validator"""

    def __init__(self, config: OAuthConfig):
        self.config = config
        self.logger = get_logger(__name__)
        self.jwks_client = None
        self._key_cache = {}
        self._cache_expiry = {}

        if config.jwks_uri:
            self.jwks_client = PyJWKClient(config.jwks_uri)

    async def validate_token(self, token: str) -> OAuthToken:
        """
        Validate OAuth 2.1 Bearer token

        Args:
            token: Bearer token string (without "Bearer " prefix)

        Returns:
            OAuthToken: Validated token with claims

        Raises:
            TokenValidationError: If token is invalid
        """
        if not self.config.enabled:
            raise TokenValidationError("OAuth is not enabled", "oauth_disabled")

        if not token:
            raise TokenValidationError("Token is required", "invalid_request")

        try:
            # Development mode: Check if token matches MCP_API_KEY directly
            if await self._validate_mcp_api_key(token):
                return self._create_mcp_api_key_token(token)

            # Step 1: Decode token header to get key ID
            unverified_header = jwt.get_unverified_header(token)
            algorithm = unverified_header.get("alg", self.config.algorithm)
            key_id = unverified_header.get("kid")

            # Step 2: Get signing key
            signing_key = await self._get_signing_key(key_id, algorithm)

            # Step 3: Validate token signature and claims
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=[algorithm],
                audience=self.config.audience if self.config.verify_audience else None,
                issuer=self.config.issuer if self.config.verify_issuer else None,
                options={
                    "verify_signature": self.config.verify_signature,
                    "verify_aud": self.config.verify_audience,
                    "verify_iss": self.config.verify_issuer,
                    "verify_exp": self.config.verify_exp,
                }
            )

            # Step 4: Create OAuthToken from payload
            oauth_token = self._create_oauth_token(token, payload)

            # Step 5: Validate scopes
            await self._validate_scopes(oauth_token)

            self.logger.debug(f"Token validated successfully for subject: {oauth_token.sub}")
            return oauth_token

        except jwt.ExpiredSignatureError:
            raise TokenValidationError("Token has expired", "invalid_token")
        except jwt.InvalidAudienceError:
            raise TokenValidationError("Invalid token audience", "invalid_token")
        except jwt.InvalidIssuerError:
            raise TokenValidationError("Invalid token issuer", "invalid_token")
        except jwt.InvalidSignatureError:
            raise TokenValidationError("Invalid token signature", "invalid_token")
        except jwt.DecodeError as e:
            raise TokenValidationError(f"Token decode error: {str(e)}", "invalid_token")
        except Exception as e:
            self.logger.error(f"Token validation error: {str(e)}")
            raise TokenValidationError(f"Token validation failed: {str(e)}", "invalid_token")

    async def _get_signing_key(self, key_id: Optional[str], algorithm: str) -> str:
        """Get JWT signing key for validation"""
        if not self.config.verify_signature:
            return ""  # Skip signature verification

        if self.jwks_client:
            try:
                # Get key from JWKS endpoint
                signing_key = self.jwks_client.get_signing_key(key_id)
                return signing_key.key
            except PyJWKClientError as e:
                raise TokenValidationError(f"Failed to get signing key: {str(e)}", "invalid_token")

        # For development/testing: use environment variable
        import os
        jwt_secret = os.getenv("JWT_SECRET")
        if jwt_secret:
            return jwt_secret

        # Development mode: use MCP_API_KEY as signing secret
        mcp_api_key = os.getenv("MCP_API_KEY")
        if mcp_api_key:
            self.logger.debug("Using MCP_API_KEY as JWT signing secret for development")
            return mcp_api_key

        raise TokenValidationError("No signing key available for token validation", "server_error")

    def _create_oauth_token(self, token: str, payload: Dict[str, Any]) -> OAuthToken:
        """Create OAuthToken from JWT payload"""
        # Extract scopes from various claim formats
        scopes = []
        if "scope" in payload:
            if isinstance(payload["scope"], str):
                scopes = payload["scope"].split()
            elif isinstance(payload["scope"], list):
                scopes = payload["scope"]
        elif "scopes" in payload:
            if isinstance(payload["scopes"], list):
                scopes = payload["scopes"]

        return OAuthToken(
            access_token=token,
            token_type="Bearer",
            sub=payload.get("sub"),
            iss=payload.get("iss"),
            aud=payload.get("aud"),
            exp=payload.get("exp"),
            iat=payload.get("iat"),
            jti=payload.get("jti"),
            scopes=scopes,
            user_id=payload.get("user_id") or payload.get("sub"),
            client_id=payload.get("client_id") or payload.get("azp"),
            scope=" ".join(scopes) if scopes else None
        )

    async def _validate_scopes(self, token: OAuthToken) -> None:
        """Validate token scopes against requirements"""
        if not self.config.required_scope:
            return  # No scope requirements

        required_scopes = self.config.required_scope.split()
        token_scopes = token.scopes or []

        # Check if token has all required scopes
        missing_scopes = set(required_scopes) - set(token_scopes)
        if missing_scopes:
            raise TokenValidationError(
                f"Token missing required scopes: {', '.join(missing_scopes)}",
                "insufficient_scope"
            )

    def extract_bearer_token(self, authorization_header: Optional[str]) -> Optional[str]:
        """
        Extract Bearer token from Authorization header

        Args:
            authorization_header: HTTP Authorization header value

        Returns:
            Token string without "Bearer " prefix, or None if not found
        """
        if not authorization_header:
            return None

        if not authorization_header.startswith("Bearer "):
            return None

        return authorization_header[7:]  # Remove "Bearer " prefix

    def create_www_authenticate_header(self, error: str = "invalid_token",
                                     description: Optional[str] = None) -> str:
        """
        Create WWW-Authenticate header for 401 responses per RFC 6750

        Args:
            error: OAuth error code
            description: Optional error description

        Returns:
            WWW-Authenticate header value
        """
        header = 'Bearer'

        if self.config.audience:
            header += f' realm="{self.config.audience}"'

        header += f' error="{error}"'

        if description:
            header += f' error_description="{description}"'

        return header

    async def validate_request_scope(self, token: OAuthToken, required_scope: str) -> bool:
        """
        Validate if token has required scope for specific request

        Args:
            token: Validated OAuth token
            required_scope: Required scope for the operation

        Returns:
            True if token has required scope, False otherwise
        """
        if not required_scope:
            return True

        return required_scope in (token.scopes or [])

    def is_token_expired(self, token: OAuthToken) -> bool:
        """Check if token is expired"""
        if not token.exp:
            return False

        return datetime.utcnow().timestamp() > token.exp

    async def _validate_mcp_api_key(self, token: str) -> bool:
        """Check if token matches MCP_API_KEY (development mode)"""
        import os
        mcp_api_key = os.getenv("MCP_API_KEY")

        if not mcp_api_key:
            return False

        # Only enable in development mode
        environment = os.getenv("ENVIRONMENT", "development")
        if environment not in ["development", "testing"]:
            return False

        return token == mcp_api_key

    def _create_mcp_api_key_token(self, token: str) -> OAuthToken:
        """Create OAuthToken for MCP API Key (development mode)"""
        import time

        return OAuthToken(
            access_token=token,
            token_type="Bearer",
            sub="mcp_api_key_user",
            iss="mcp_development",
            aud=self.config.audience or "mcp_server",
            exp=int(time.time()) + 3600,  # 1 hour expiry
            iat=int(time.time()),
            scopes=["mcp:read", "mcp:write", "mcp:admin"],  # Full access in dev mode
            user_id="mcp_api_key_user",
            client_id="mcp_development",
            scope="mcp:read mcp:write mcp:admin"
        )