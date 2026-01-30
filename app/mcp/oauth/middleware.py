"""
OAuth 2.1 FastAPI Middleware and Dependencies
Provides OAuth integration for Claude Connectors
"""
from typing import Optional, Callable, Annotated
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .token_validator import TokenValidator, TokenValidationError
from .models import OAuthToken
from app.config.app_config import OAuthConfig, get_app_config
from app.config.logging_config import get_logger


# Global OAuth configuration and validator instances
_oauth_config: Optional[OAuthConfig] = None
_token_validator: Optional[TokenValidator] = None

def initialize_oauth(config: OAuthConfig) -> None:
    """Initialize global OAuth configuration"""
    global _oauth_config, _token_validator
    _oauth_config = config
    if config.enabled:
        _token_validator = TokenValidator(config)


def get_oauth_config() -> OAuthConfig:
    """Get current OAuth configuration"""
    global _oauth_config
    if _oauth_config is None:
        _oauth_config = get_app_config().oauth
    return _oauth_config


def get_token_validator() -> Optional[TokenValidator]:
    """Get current token validator"""
    global _token_validator
    return _token_validator


# FastAPI Security Scheme
oauth2_scheme = HTTPBearer(auto_error=False)


async def optional_oauth_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme)
) -> Optional[OAuthToken]:
    """
    Optional OAuth token dependency - returns None if no token or OAuth disabled

    Use this for endpoints that support both authenticated and unauthenticated access
    """
    config = get_oauth_config()

    if not config.enabled:
        return None

    if not credentials:
        return None

    validator = get_token_validator()
    if not validator:
        return None

    try:
        token = await validator.validate_token(credentials.credentials)
        return token
    except TokenValidationError:
        # Log the error but don't raise for optional auth
        logger = get_logger(__name__)
        logger.warning("Invalid token provided for optional auth")
        return None


async def validated_oauth_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme)
) -> Optional[OAuthToken]:
    """
    Validated OAuth token dependency - enforces token validation if provided

    If Authorization header is present, token MUST be valid (raises 401 if invalid)
    If no Authorization header, returns None (backwards compatible)

    Use this for endpoints that want to enforce OAuth when used, but allow no-auth access
    """
    config = get_oauth_config()

    # No credentials provided - allow for backwards compatibility
    if not credentials:
        return None

    # Credentials provided - MUST be valid
    # Create validator if needed (even if OAuth disabled, for MCP_API_KEY validation)
    validator = get_token_validator()
    if not validator:
        # Create a validator even when OAuth is disabled to handle MCP_API_KEY
        validator = TokenValidator(config)

    try:
        token = await validator.validate_token(credentials.credentials)
        return token
    except TokenValidationError as e:
        # Token was provided but is INVALID - reject the request
        logger = get_logger(__name__)
        logger.warning(f"OAuth token validation failed - error_code: {e.error_code}, message: {e.message}, token_prefix: {credentials.credentials[:20]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e.message}",
            headers={"WWW-Authenticate": validator.create_www_authenticate_header(e.error_code, e.message)}
        )


async def required_oauth_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme)
) -> OAuthToken:
    """
    Required OAuth token dependency - raises 401 if no valid token

    Use this for endpoints that require authentication
    """
    config = get_oauth_config()

    if not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="OAuth authentication is not configured"
        )

    validator = get_token_validator()
    if not validator:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OAuth validator not available"
        )

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": validator.create_www_authenticate_header("invalid_request", "Bearer token required")}
        )

    try:
        token = await validator.validate_token(credentials.credentials)
        return token
    except TokenValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.message,
            headers={"WWW-Authenticate": validator.create_www_authenticate_header(e.error_code, e.message)}
        )


async def oauth_token_with_scope(required_scope: str):
    """
    Create OAuth dependency that requires specific scope

    Args:
        required_scope: Required OAuth scope (e.g., "mcp:write")

    Returns:
        FastAPI dependency function
    """
    async def check_scope(token: OAuthToken = Depends(required_oauth_token)) -> OAuthToken:
        validator = get_token_validator()
        if validator and not await validator.validate_request_scope(token, required_scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required scope '{required_scope}' not found in token",
                headers={"WWW-Authenticate": validator.create_www_authenticate_header(
                    "insufficient_scope",
                    f"Required scope '{required_scope}' not found in token"
                )}
            )
        return token

    return check_scope


# Convenience type annotations for dependencies
OptionalOAuthToken = Annotated[Optional[OAuthToken], Depends(optional_oauth_token)]
ValidatedOAuthToken = Annotated[Optional[OAuthToken], Depends(validated_oauth_token)]
RequiredOAuthToken = Annotated[OAuthToken, Depends(required_oauth_token)]


class OAuthMiddleware:
    """
    FastAPI Middleware for OAuth 2.1 support

    Handles OAuth configuration and provides backwards compatibility
    """

    def __init__(self, config: OAuthConfig):
        self.config = config
        self.logger = get_logger(__name__)

        # Initialize global OAuth state
        initialize_oauth(config)

    def is_oauth_protected_endpoint(self, path: str) -> bool:
        """Check if endpoint requires OAuth protection"""
        # OAuth-protected endpoints
        protected_paths = [
            "/oauth",  # OAuth-protected MCP endpoint
            "/oauth/",
            "/.well-known/oauth-protected-resource"
        ]

        return any(path.startswith(protected_path) for protected_path in protected_paths)

    def is_backwards_compatible_endpoint(self, path: str) -> bool:
        """Check if endpoint supports backwards compatibility (no OAuth required)"""
        compatible_paths = [
            "/",      # Original MCP endpoint
            "/health",
            "/docs",
            "/openapi.json"
        ]

        return any(path == compatible_path for compatible_path in compatible_paths)

    async def __call__(self, request: Request, call_next: Callable):
        """Middleware execution"""
        response = await call_next(request)

        # Add OAuth headers if enabled
        if self.config.enabled:
            # Add CORS headers for OAuth
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"

        return response


def create_protected_resource_metadata_response(config: Optional[OAuthConfig] = None, base_url: Optional[str] = None) -> dict:
    """Create OAuth 2.1 Protected Resource Metadata response"""
    if config is None:
        config = get_oauth_config()
    return config.get_protected_resource_metadata(base_url=base_url)


# Scope validation helpers
async def require_mcp_read_scope(token: RequiredOAuthToken) -> OAuthToken:
    """Require mcp:read scope"""
    return await oauth_token_with_scope("mcp:read")(token)


async def require_mcp_write_scope(token: RequiredOAuthToken) -> OAuthToken:
    """Require mcp:write scope"""
    return await oauth_token_with_scope("mcp:write")(token)


async def require_mcp_admin_scope(token: RequiredOAuthToken) -> OAuthToken:
    """Require mcp:admin scope"""
    return await oauth_token_with_scope("mcp:admin")(token)


# Type annotations for scope-specific dependencies
MCPReadToken = Annotated[OAuthToken, Depends(require_mcp_read_scope)]
MCPWriteToken = Annotated[OAuthToken, Depends(require_mcp_write_scope)]
MCPAdminToken = Annotated[OAuthToken, Depends(require_mcp_admin_scope)]