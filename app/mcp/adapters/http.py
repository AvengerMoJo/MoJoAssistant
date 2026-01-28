"""
HTTP Protocol Adapter for Web/Mobile clients with OAuth 2.1 support
File: app/mcp/adapters/http.py
"""

import json
import time
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.mcp.adapters.base import ProtocolAdapter
from app.mcp.core.models import MCPRequest, MCPResponse
from app.config.app_config import get_app_config
from app.mcp.oauth.middleware import (
    OAuthMiddleware,
    OptionalOAuthToken,
    ValidatedOAuthToken,
    RequiredOAuthToken,
    create_protected_resource_metadata_response,
)
from app.mcp.oauth import endpoints as oauth_endpoints


class HTTPAdapter(ProtocolAdapter):
    """Simple HTTP protocol adapter using FastAPI"""

    def __init__(self, engine, config: Dict[str, Any]):
        self.engine = engine
        self.config = config
        self.app = None
        self.logger = None

        # Initialize OAuth configuration
        self.oauth_config = get_app_config().oauth

        # Check MCP_REQUIRE_AUTH and OAUTH_ENABLED settings
        # Only use OAuth if BOTH conditions are met:
        # 1. OAUTH_ENABLED = true
        # 2. Either MCP_REQUIRE_AUTH = false OR OAuth is properly configured
        from app.config.mcp_config import get_mcp_auth_config

        mcp_require_auth, mcp_api_key = get_mcp_auth_config()

        # Store authentication configuration as instance variables
        self.mcp_require_auth = mcp_require_auth
        self.mcp_api_key_expected = mcp_api_key

        use_oauth = self.oauth_config.enabled and (
            not mcp_require_auth
            or (self.oauth_config.issuer and self.oauth_config.audience)
        )

        self.oauth_enabled = use_oauth

    def set_logger(self, logger):
        self.logger = logger

    def create_app(self):
        """Create FastAPI application with OAuth 2.1 support"""
        app = FastAPI(
            title="MoJoAssistant MCP Server",
            version="1.0.0",
            description="MCP Server with OAuth 2.1 support for Claude Connectors",
        )

        # Enhanced CORS for OAuth
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*", "Authorization"],  # Include Authorization header
        )

        # Initialize OAuth middleware if enabled
        if self.oauth_config.enabled:
            oauth_middleware = OAuthMiddleware(self.oauth_config)
            app.middleware("http")(oauth_middleware)

        # Add startup and shutdown event handlers
        @app.on_event("startup")
        async def startup_event():
            """Application startup event handler"""
            if self.logger:
                self.logger.info("MCP Server startup initiated")

                # Log configuration status
                self.logger.info(f"OAuth enabled: {self.oauth_config.enabled}")
                if self.oauth_config.enabled:
                    self.logger.info(f"OAuth issuer: {self.oauth_config.issuer}")
                    self.logger.info(f"OAuth audience: {self.oauth_config.audience}")

                # Initialize memory system if needed
                try:
                    if hasattr(self.engine, "memory_service"):
                        # Memory service is initialized in __init__, just log status
                        if hasattr(self.engine.memory_service, "multi_model_enabled"):
                            multi_enabled = (
                                self.engine.memory_service.multi_model_enabled
                            )
                            self.logger.info(
                                f"Memory service ready (multi-model: {multi_enabled})"
                            )
                        else:
                            self.logger.info("Memory service ready")

                    if hasattr(self.engine, "knowledge_service"):
                        # Knowledge service typically doesn't need explicit initialization
                        self.logger.info("Knowledge service ready")

                    self.logger.info("MCP Server startup complete")
                except Exception as e:
                    self.logger.error(f"Error during startup initialization: {e}")

        @app.on_event("shutdown")
        async def shutdown_event():
            """Application shutdown event handler"""
            if self.logger:
                self.logger.info("MCP Server shutdown initiated")

                # Cleanup memory system
                try:
                    if hasattr(self.engine, "memory_service"):
                        # Check if memory service has explicit cleanup methods
                        if hasattr(self.engine.memory_service, "close"):
                            await self.engine.memory_service.close()
                        elif hasattr(self.engine.memory_service, "cleanup"):
                            await self.engine.memory_service.cleanup()
                        self.logger.info("Memory service cleanup complete")

                    if hasattr(self.engine, "knowledge_service"):
                        # Check if knowledge service has explicit cleanup methods
                        if hasattr(self.engine.knowledge_service, "close"):
                            await self.engine.knowledge_service.close()
                        elif hasattr(self.engine.knowledge_service, "cleanup"):
                            await self.engine.knowledge_service.cleanup()
                        self.logger.info("Knowledge service cleanup complete")

                    self.logger.info("MCP Server shutdown complete")
                except Exception as e:
                    self.logger.error(f"Error during shutdown cleanup: {e}")

        # OAuth 2.1 Protected Resource Metadata endpoint
        @app.get("/.well-known/oauth-protected-resource")
        async def oauth_protected_resource_metadata(request: Request):
            """OAuth 2.1 Protected Resource Metadata per RFC"""
            if not self.oauth_config.enabled:
                return JSONResponse(
                    content={"error": "OAuth not enabled"}, status_code=501
                )
            # Get base URL from request
            base_url = f"{request.url.scheme}://{request.url.netloc}"
            return create_protected_resource_metadata_response(self.oauth_config, base_url)

        # OAuth-protected MCP endpoint for Claude Connectors
        @app.post("/oauth")
        async def handle_oauth_mcp_request(
            raw_request: Request, token: RequiredOAuthToken
        ):
            """OAuth-protected MCP endpoint for Claude Connectors"""
            return await self._process_mcp_request(raw_request, token.user_id)

        # Root GET endpoint - Server info and OAuth discovery
        @app.get("/")
        async def root_info():
            """Root endpoint - provides server info"""
            info = {
                "name": "MoJoAssistant MCP Server",
                "version": "1.0.0",
                "status": "running",
                "protocol": "MCP",
                "endpoints": {
                    "mcp": "POST /",
                    "oauth_mcp": "POST /oauth",
                    "health": "GET /health",
                },
            }

            # Add OAuth discovery if enabled
            if self.oauth_config.enabled and self.oauth_config.authorization_endpoint:
                info["oauth"] = {
                    "enabled": True,
                    "discovery": "GET /.well-known/oauth-authorization-server",
                }

            return info

        # Original MCP endpoint - validates OAuth if provided
        @app.post("/")
        async def handle_mcp_request(
            raw_request: Request,
            token: ValidatedOAuthToken = None,
            mcp_api_key: Optional[str] = Header(None, alias="MCP-API-Key"),
            mcp_env_api_key: Optional[str] = Header(None, alias="MCP_API_KEY"),
            authorization: Optional[str] = Header(None),
        ):
            """
            Original MCP endpoint - enforces authentication based on MCP_REQUIRE_AUTH

            Authentication logic:
            - If MCP_REQUIRE_AUTH=true: Requires EITHER valid OAuth token OR valid MCP-API-Key
            - If MCP_REQUIRE_AUTH=false: Allows all requests (no auth required)
            - Special case: When OAuth enabled, allow requests with NO credentials (for OAuth discovery)
              but still validate credentials if they ARE provided
            """
            # Check if authentication is required
            if self.mcp_require_auth:
                # Extract provided API key from headers
                provided_api_key = mcp_api_key or mcp_env_api_key

                # Check what credentials were provided
                has_valid_oauth = token is not None
                has_valid_api_key = provided_api_key and provided_api_key == self.mcp_api_key_expected
                has_any_credentials = (token is not None) or (provided_api_key is not None)

                # Decision logic when MCP_REQUIRE_AUTH=true:
                # 1. Valid OAuth token → Allow
                # 2. Valid API key → Allow
                # 3. No valid credentials → Block
                #
                # Note: OAuth discovery endpoints (/.well-known/*) are separate routes
                # and don't go through this check, so OAuth flow can still complete

                if has_valid_oauth or has_valid_api_key:
                    # Valid authentication provided
                    if self.logger:
                        auth_method = "OAuth" if has_valid_oauth else "API key"
                        self.logger.debug(f"Request authenticated via {auth_method}")
                else:
                    # Block: no valid credentials provided
                    from fastapi import HTTPException, status
                    if self.logger:
                        self.logger.warning(f"MCP_REQUIRE_AUTH blocked: has_oauth={has_valid_oauth}, has_api_key={bool(provided_api_key)}, api_key_valid={has_valid_api_key}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Authentication required: provide valid Bearer token or MCP-API-Key header",
                        headers={"WWW-Authenticate": 'Bearer realm="MCP Server"'}
                    )

            user_id = token.user_id if token else None
            return await self._process_mcp_request(raw_request, user_id)

        # Include OAuth Authorization Server endpoints if enabled
        if self.oauth_config.enabled and self.oauth_config.enable_authorization_server:
            app.include_router(oauth_endpoints.router)
            if self.logger:
                self.logger.info("OAuth Authorization Server endpoints enabled")

        @app.get("/health")
        async def health_check():
            uptime = time.time() - self.engine.start_time
            return {"status": "healthy", "uptime": round(uptime, 2)}

        self.app = app
        return app

    async def _process_mcp_request(
        self, raw_request: Request, user_id: Optional[str] = None
    ) -> JSONResponse:
        """
        Shared MCP request processing logic

        Args:
            raw_request: FastAPI Request object
            user_id: Optional user ID from OAuth token (for audit/isolation)

        Returns:
            JSONResponse: MCP response
        """
        try:
            body = await raw_request.json()

            # Validate JSON-RPC 2.0 format
            if not isinstance(body, dict):
                return JSONResponse(
                    content={
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32600, "message": "Invalid Request"},
                    },
                    status_code=400,
                )

            if "jsonrpc" not in body or body.get("jsonrpc") != "2.0":
                return JSONResponse(
                    content={
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "error": {"code": -32600, "message": "Invalid Request"},
                    },
                    status_code=400,
                )

            if "method" not in body:
                return JSONResponse(
                    content={
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "error": {"code": -32600, "message": "Invalid Request"},
                    },
                    status_code=400,
                )

            # Create MCP request with optional user context
            mcp_request = MCPRequest(
                method=body.get("method", ""),
                params=body.get("params", {}),
                request_id=body.get("id"),
                auth_token=user_id,  # Use user_id for context
            )

            if self.logger:
                auth_info = f" (user: {user_id})" if user_id else ""
                self.logger.debug(f"HTTP received: {mcp_request.method}{auth_info}")

            mcp_response = await self.engine.process_request(mcp_request)

            if mcp_response is None:
                return JSONResponse(content={}, status_code=202)

            return JSONResponse(content=mcp_response.to_dict())

        except json.JSONDecodeError:
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                },
                status_code=400,
            )
        except Exception as e:
            if self.logger:
                self.logger.error(f"HTTP request error: {e}")
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": "Internal error"},
                },
                status_code=500,
            )

    async def receive_request(self) -> Optional[MCPRequest]:
        raise NotImplementedError("HTTP adapter uses FastAPI for request handling")

    async def send_response(self, response: Optional[MCPResponse]):
        raise NotImplementedError("HTTP adapter uses FastAPI for response handling")

    async def run(self, host: str = "0.0.0.0", port: int = 8000):
        """Run HTTP server"""
        import uvicorn

        if not self.app:
            self.app = self.create_app()

        if self.logger:
            self.logger.info(f"Starting HTTP server on {host}:{port}")

        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)

        try:
            await server.serve()
        except Exception as e:
            if self.logger:
                self.logger.error(f"HTTP server error: {e}")
            raise
