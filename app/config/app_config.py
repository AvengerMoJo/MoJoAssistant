"""
Unified Application Configuration System
Centralized configuration management for MoJoAssistant
"""
import os
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from pathlib import Path
# Import with fallback for environments without python-dotenv
try:
    from dotenv import load_dotenv
except ImportError:
    # Fallback if python-dotenv is not available
    def load_dotenv(*args, **kwargs):
        pass


@dataclass
class ServerConfig:
    """HTTP Server configuration"""
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = field(default_factory=lambda: ["*"])
    api_key: Optional[str] = None
    require_auth: bool = False


@dataclass
class OAuthConfig:
    """OAuth 2.1 configuration"""
    enabled: bool = False
    issuer: Optional[str] = None
    audience: Optional[str] = None
    jwks_uri: Optional[str] = None

    # Authorization Server Endpoints
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None

    # Resource Server Settings
    resource_server_id: Optional[str] = None

    # Token validation settings
    verify_signature: bool = True
    verify_audience: bool = True
    verify_issuer: bool = True
    verify_exp: bool = True

    # Scopes
    supported_scopes: List[str] = field(default_factory=lambda: ["mcp:read", "mcp:write", "mcp:admin"])
    required_scope: Optional[str] = "mcp:read"

    # Advanced settings
    algorithm: str = "RS256"
    token_cache_ttl: int = 300

    def get_protected_resource_metadata(self) -> Dict[str, Any]:
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


@dataclass
class LLMConfig:
    """LLM provider configuration"""
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    local_model_path: Optional[str] = None


@dataclass
class SearchConfig:
    """Search service configuration"""
    google_api_key: Optional[str] = None
    google_search_engine_id: Optional[str] = None
    enabled: bool = True


@dataclass
class MemoryConfig:
    """Memory system configuration"""
    embedding_model: str = "all-MiniLM-L6-v2"
    multi_model_enabled: bool = False
    vector_store: str = "qdrant"
    memory_path: str = ".memory"
    knowledge_path: str = ".knowledge"
    max_context_items: int = 10
    embedding_cache_ttl: int = 3600


@dataclass
class LoggingConfig:
    """Logging configuration"""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: Optional[str] = None
    enable_console: bool = True


@dataclass
class AppConfig:
    """Unified Application Configuration"""

    # Sub-configurations
    server: ServerConfig = field(default_factory=ServerConfig)
    oauth: OAuthConfig = field(default_factory=OAuthConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # Environment info
    environment: str = "development"
    debug: bool = False

    @classmethod
    def from_env(cls, env_path: Optional[str] = None) -> 'AppConfig':
        """Load configuration from environment variables and .env file"""

        # Load .env file
        if env_path is None:
            env_path = Path(__file__).parent.parent.parent / '.env'

        if env_path and Path(env_path).exists():
            load_dotenv(env_path)

        # Create configuration from environment
        return cls(
            server=ServerConfig(
                host=os.getenv("SERVER_HOST", "0.0.0.0"),
                port=int(os.getenv("SERVER_PORT", "8000")),
                cors_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                api_key=os.getenv("MCP_API_KEY"),
                require_auth=os.getenv("MCP_REQUIRE_AUTH", "false").lower() in ("true", "1", "yes")
            ),

            oauth=OAuthConfig(
                enabled=os.getenv("OAUTH_ENABLED", "false").lower() in ("true", "1", "yes"),
                issuer=os.getenv("OAUTH_ISSUER"),
                audience=os.getenv("OAUTH_AUDIENCE"),
                jwks_uri=os.getenv("OAUTH_JWKS_URI"),
                authorization_endpoint=os.getenv("OAUTH_AUTHORIZATION_ENDPOINT"),
                token_endpoint=os.getenv("OAUTH_TOKEN_ENDPOINT"),
                resource_server_id=os.getenv("OAUTH_RESOURCE_SERVER_ID"),
                verify_signature=os.getenv("OAUTH_VERIFY_SIGNATURE", "true").lower() in ("true", "1", "yes"),
                verify_audience=os.getenv("OAUTH_VERIFY_AUDIENCE", "true").lower() in ("true", "1", "yes"),
                verify_issuer=os.getenv("OAUTH_VERIFY_ISSUER", "true").lower() in ("true", "1", "yes"),
                verify_exp=os.getenv("OAUTH_VERIFY_EXP", "true").lower() in ("true", "1", "yes"),
                supported_scopes=os.getenv("OAUTH_SUPPORTED_SCOPES", "mcp:read,mcp:write,mcp:admin").split(","),
                required_scope=os.getenv("OAUTH_REQUIRED_SCOPE"),
                algorithm=os.getenv("OAUTH_ALGORITHM", "RS256"),
                token_cache_ttl=int(os.getenv("OAUTH_TOKEN_CACHE_TTL", "300"))
            ),

            llm=LLMConfig(
                openai_api_key=os.getenv("OPENAI_API_KEY"),
                anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
                google_api_key=os.getenv("GOOGLE_API_KEY"),
                openrouter_api_key=os.getenv("OPEN_ROUTER_KEY"),
                local_model_path=os.getenv("LOCAL_MODEL_PATH")
            ),

            search=SearchConfig(
                google_api_key=os.getenv("GOOGLE_API_KEY"),
                google_search_engine_id=os.getenv("GOOGLE_SEARCH_ENGINE_ID"),
                enabled=os.getenv("SEARCH_ENABLED", "true").lower() in ("true", "1", "yes")
            ),

            memory=MemoryConfig(
                embedding_model=os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
                multi_model_enabled=os.getenv("MULTI_MODEL_ENABLED", "false").lower() in ("true", "1", "yes"),
                vector_store=os.getenv("VECTOR_STORE", "qdrant"),
                memory_path=os.getenv("MEMORY_PATH", ".memory"),
                knowledge_path=os.getenv("KNOWLEDGE_PATH", ".knowledge"),
                max_context_items=int(os.getenv("MAX_CONTEXT_ITEMS", "10")),
                embedding_cache_ttl=int(os.getenv("EMBEDDING_CACHE_TTL", "3600"))
            ),

            logging=LoggingConfig(
                level=os.getenv("LOG_LEVEL", "INFO").upper(),
                format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
                file_path=os.getenv("LOG_FILE"),
                enable_console=os.getenv("LOG_CONSOLE", "true").lower() in ("true", "1", "yes")
            ),

            environment=os.getenv("ENVIRONMENT", "development"),
            debug=os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
        )

    def get_oauth_protected_resource_metadata(self) -> Dict[str, Any]:
        """Generate OAuth 2.1 Protected Resource Metadata"""
        return self.oauth.get_protected_resource_metadata()

    def is_oauth_valid(self) -> bool:
        """Check if OAuth configuration is valid"""
        return self.oauth.is_valid()

    def is_search_enabled(self) -> bool:
        """Check if web search is properly configured"""
        return (
            self.search.enabled and
            self.search.google_api_key is not None and
            self.search.google_search_engine_id is not None
        )

    def validate(self) -> List[str]:
        """Validate configuration and return list of issues"""
        issues = []

        # OAuth validation
        if self.oauth.enabled and not self.is_oauth_valid():
            issues.append("OAuth is enabled but missing required configuration (issuer, audience, jwks_uri)")

        # Server validation
        if self.server.port < 1 or self.server.port > 65535:
            issues.append(f"Invalid server port: {self.server.port}")

        # Memory validation
        if not Path(self.memory.memory_path).exists():
            issues.append(f"Memory path does not exist: {self.memory.memory_path}")

        # Search validation
        if self.search.enabled and not self.is_search_enabled():
            issues.append("Search is enabled but missing Google API configuration")

        return issues

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excluding sensitive data)"""
        return {
            "server": {
                "host": self.server.host,
                "port": self.server.port,
                "cors_origins": self.server.cors_origins,
                "require_auth": self.server.require_auth,
                "api_key_configured": bool(self.server.api_key)
            },
            "oauth": {
                "enabled": self.oauth.enabled,
                "issuer": self.oauth.issuer,
                "audience": self.oauth.audience,
                "supported_scopes": self.oauth.supported_scopes,
                "required_scope": self.oauth.required_scope,
                "algorithm": self.oauth.algorithm
            },
            "search": {
                "enabled": self.search.enabled,
                "configured": self.is_search_enabled()
            },
            "memory": {
                "embedding_model": self.memory.embedding_model,
                "multi_model_enabled": self.memory.multi_model_enabled,
                "vector_store": self.memory.vector_store,
                "max_context_items": self.memory.max_context_items
            },
            "environment": self.environment,
            "debug": self.debug
        }


# Global configuration instance
_app_config: Optional[AppConfig] = None


def get_app_config() -> AppConfig:
    """Get global application configuration"""
    global _app_config
    if _app_config is None:
        _app_config = AppConfig.from_env()
    return _app_config


def reload_config(env_path: Optional[str] = None) -> AppConfig:
    """Reload configuration from environment"""
    global _app_config
    _app_config = AppConfig.from_env(env_path)
    return _app_config