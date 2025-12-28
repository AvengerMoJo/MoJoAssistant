"""
OAuth 2.1 configuration management
"""
import os
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class OAuthConfig:
    """OAuth 2.1 configuration settings"""

    # OAuth Enable/Disable
    enabled: bool = False

    # Authorization Server Settings
    issuer: Optional[str] = None
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    jwks_uri: Optional[str] = None

    # Resource Server Settings
    audience: Optional[str] = None
    resource_server_id: Optional[str] = None

    # Token Validation
    verify_signature: bool = True
    verify_audience: bool = True
    verify_issuer: bool = True
    verify_exp: bool = True

    # Supported Scopes
    supported_scopes: List[str] = None
    required_scope: Optional[str] = None

    # Advanced Settings
    algorithm: str = "RS256"
    token_cache_ttl: int = 300  # 5 minutes

    def __post_init__(self):
        if self.supported_scopes is None:
            self.supported_scopes = ["mcp:read", "mcp:write", "mcp:admin"]

    @classmethod
    def from_env(cls) -> 'OAuthConfig':
        """Load OAuth configuration from environment variables"""
        return cls(
            enabled=os.getenv("OAUTH_ENABLED", "false").lower() in ("true", "1", "yes"),
            issuer=os.getenv("OAUTH_ISSUER"),
            authorization_endpoint=os.getenv("OAUTH_AUTHORIZATION_ENDPOINT"),
            token_endpoint=os.getenv("OAUTH_TOKEN_ENDPOINT"),
            jwks_uri=os.getenv("OAUTH_JWKS_URI"),
            audience=os.getenv("OAUTH_AUDIENCE"),
            resource_server_id=os.getenv("OAUTH_RESOURCE_SERVER_ID"),
            verify_signature=os.getenv("OAUTH_VERIFY_SIGNATURE", "true").lower() in ("true", "1", "yes"),
            verify_audience=os.getenv("OAUTH_VERIFY_AUDIENCE", "true").lower() in ("true", "1", "yes"),
            verify_issuer=os.getenv("OAUTH_VERIFY_ISSUER", "true").lower() in ("true", "1", "yes"),
            verify_exp=os.getenv("OAUTH_VERIFY_EXP", "true").lower() in ("true", "1", "yes"),
            supported_scopes=os.getenv("OAUTH_SUPPORTED_SCOPES", "mcp:read,mcp:write,mcp:admin").split(","),
            required_scope=os.getenv("OAUTH_REQUIRED_SCOPE"),
            algorithm=os.getenv("OAUTH_ALGORITHM", "RS256"),
            token_cache_ttl=int(os.getenv("OAUTH_TOKEN_CACHE_TTL", "300"))
        )

    def get_protected_resource_metadata(self) -> dict:
        """Generate OAuth 2.1 Protected Resource Metadata"""
        metadata = {
            "authorization_servers": []
        }

        if self.issuer:
            # Standard OAuth 2.1 authorization server metadata URL
            auth_server_url = f"{self.issuer.rstrip('/')}/.well-known/oauth-authorization-server"
            metadata["authorization_servers"].append(auth_server_url)

        if self.resource_server_id:
            metadata["resource_server"] = self.resource_server_id

        if self.supported_scopes:
            metadata["scopes_supported"] = self.supported_scopes

        return metadata

    def is_valid(self) -> bool:
        """Check if OAuth configuration is valid"""
        if not self.enabled:
            return True  # Valid to be disabled

        # Required fields when OAuth is enabled
        required_fields = [self.issuer, self.audience]

        # Need either JWKS URI or token endpoint for validation
        has_validation_endpoint = self.jwks_uri or self.token_endpoint

        return all(field is not None for field in required_fields) and has_validation_endpoint