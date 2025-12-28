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
        default=None,
        description="Resource server identifier"
    )
    scopes_supported: List[str] = Field(
        default_factory=lambda: ["mcp:read", "mcp:write"],
        description="List of OAuth scopes supported"
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