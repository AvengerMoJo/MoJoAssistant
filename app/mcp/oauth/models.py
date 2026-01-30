"""
OAuth 2.1 data models and schemas
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class OAuthToken(BaseModel):
    """OAuth 2.1 token representation"""

    access_token: str
    token_type: str = "Bearer"
    expires_in: Optional[int] = None
    refresh_token: Optional[str] = None
    scope: Optional[str] = None

    # JWT Claims
    sub: Optional[str] = None  # Subject (user ID)
    iss: Optional[str] = None  # Issuer
    aud: Optional[str] = None  # Audience
    exp: Optional[int] = None  # Expiration time
    iat: Optional[int] = None  # Issued at
    jti: Optional[str] = None  # JWT ID

    # Additional claims
    scopes: List[str] = Field(default_factory=list)
    user_id: Optional[str] = None
    client_id: Optional[str] = None


class OAuthError(BaseModel):
    """OAuth 2.1 error response"""

    error: str
    error_description: Optional[str] = None
    error_uri: Optional[str] = None
    state: Optional[str] = None


class ProtectedResourceMetadata(BaseModel):
    """OAuth 2.1 Protected Resource Metadata"""

    authorization_servers: List[str] = Field(
        description="List of authorization server metadata URLs"
    )
    resource_server: Optional[str] = Field(
        default=None, description="Resource server identifier"
    )
    scopes_supported: List[str] = Field(
        default_factory=lambda: ["mcp:read", "mcp:write"],
        description="List of OAuth scopes supported",
    )


class TokenIntrospectionRequest(BaseModel):
    """OAuth 2.1 Token Introspection Request"""

    token: str
    token_type_hint: Optional[str] = None


class TokenIntrospectionResponse(BaseModel):
    """OAuth 2.1 Token Introspection Response"""

    active: bool
    scope: Optional[str] = None
    client_id: Optional[str] = None
    username: Optional[str] = None
    token_type: Optional[str] = None
    exp: Optional[int] = None
    iat: Optional[int] = None
    sub: Optional[str] = None
    aud: Optional[str] = None
    iss: Optional[str] = None
    jti: Optional[str] = None


class AuthorizationServerMetadata(BaseModel):
    """OAuth 2.1 Authorization Server Metadata (RFC 8414)"""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: Optional[str] = None
    response_types_supported: List[str] = Field(default_factory=lambda: ["code"])
    grant_types_supported: List[str] = Field(
        default_factory=lambda: ["authorization_code", "refresh_token"]
    )
    code_challenge_methods_supported: List[str] = Field(
        default_factory=lambda: ["S256"]
    )
    token_endpoint_auth_methods_supported: List[str] = Field(
        default_factory=lambda: ["none"]
    )
    scopes_supported: List[str] = Field(
        default_factory=lambda: ["mcp:read", "mcp:write", "mcp:admin"]
    )


class AuthorizationRequest(BaseModel):
    """OAuth 2.1 Authorization Request"""

    response_type: str  # "code"
    client_id: Optional[str] = None  # Optional for public clients
    redirect_uri: str
    scope: Optional[str] = None
    state: str
    code_challenge: str
    code_challenge_method: str  # "S256"


class TokenRequest(BaseModel):
    """OAuth 2.1 Token Request"""

    grant_type: str  # "authorization_code" or "refresh_token"
    code: Optional[str] = None  # For authorization_code grant
    redirect_uri: Optional[str] = None  # For authorization_code grant
    code_verifier: Optional[str] = None  # For PKCE verification
    refresh_token: Optional[str] = None  # For refresh_token grant
    client_id: Optional[str] = None  # Optional for public clients
    client_secret: Optional[str] = None  # Optional


class TokenResponse(BaseModel):
    """OAuth 2.1 Token Response"""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
