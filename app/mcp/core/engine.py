"""
Core MCP Engine - Protocol-agnostic request processing
File: app/mcp/core/engine.py
"""

import time
from typing import Dict, Any, Optional
from app.mcp.core.models import MCPRequest, MCPResponse, ErrorCode
from app.mcp.core.tools import ToolRegistry
from app.config.logging_config import get_logger
from app.config.paths import get_memory_path


class MCPEngine:
    """Core MCP processing engine"""

    def __init__(self, memory_service=None, config: Dict[str, Any] = None):
        self.memory_service = memory_service
        self.config = config or {}
        self.logger = None
        self.tool_registry = None
        self.start_time = time.time()
        self.initialized = False

    async def initialize(self):
        """Initialize the engine"""
        if self.initialized:
            return

        from app.config.logging_config import setup_logging

        setup_logging()
        self.logger = get_logger(__name__)
        self.logger.info("Initializing MCP Engine")

        if not self.memory_service:
            from app.services.memory_backend import create_hybrid_memory_service
            from app.config.config_loader import load_embedding_config

            # Pull the merged embedding config (system + ~/.memory overlay).
            # The file-based config is the source of truth for backend-specific
            # fields (server_url, api_key, request_format, dimensions, ...).
            try:
                merged = load_embedding_config()
                embed_default = dict(merged.get("embedding_models", {}).get("default", {}))
            except Exception as e:
                self.logger.warning("Failed to load embedding_config.json, falling back to env: %s", e)
                merged, embed_default = None, {}

            # Layered: env-driven app_config values win over file-based values
            # for the 3 known fields, so EMBEDDING_MODEL / EMBEDDING_BACKEND
            # env vars still take precedence when explicitly set.
            env_model = self.config.get("embedding_model", "BAAI/bge-m3")
            env_backend = self.config.get("embedding_backend", "huggingface")
            env_device = self.config.get("embedding_device")

            embedding_model = env_model or embed_default.get("model_name", "BAAI/bge-m3")
            embedding_backend = env_backend or embed_default.get("backend", "huggingface")
            embedding_device = env_device or embed_default.get("device")

            # Forward the rest of the file-based config as backend kwargs.
            extras: Dict[str, Any] = {}
            for k, v in embed_default.items():
                if k not in {"model_name", "backend", "device"}:
                    extras[k] = v
            # Merge memory_settings (working_memory_max_tokens, data_directory, ...)
            # into the config dict so MemoryService picks it up.
            effective_config = dict(self.config) if isinstance(self.config, dict) else self.config
            if merged and "memory_settings" in merged:
                if isinstance(effective_config, dict):
                    effective_config = {**effective_config, **merged["memory_settings"]}
                else:
                    # effective_config is an AppConfig dataclass; fall back to
                    # leaving it untouched if we can't merge cleanly.
                    pass

            self.memory_service = create_hybrid_memory_service(
                data_dir=get_memory_path(),
                config=effective_config,
                embedding_model=embedding_model,
                embedding_backend=embedding_backend,
                embedding_device=embedding_device,
                **extras,
            )
            self.logger.info(f"Memory service initialized with embedding: {embedding_backend}/{embedding_model}")

        self.tool_registry = ToolRegistry(self.memory_service, self.config)
        self.logger.info(
            f"Tool registry initialized with {len(self.tool_registry.get_tools())} tools"
        )

        self.initialized = True

    async def process_request(self, request: MCPRequest) -> Optional[MCPResponse]:
        """Core request processing - protocol-agnostic"""
        if not self.initialized:
            await self.initialize()

        try:
            if request.method == "initialize":
                return await self._handle_initialize(request)
            elif request.method == "tools/list":
                return await self._handle_tools_list(request)
            elif request.method == "tools/call":
                return await self._handle_tool_call(request)
            elif request.method.startswith("notifications/"):
                self.logger.info(f"Received notification: {request.method}")
                return None
            else:
                return MCPResponse.make_error(
                    request.request_id,
                    ErrorCode.METHOD_NOT_FOUND,
                    f"Unknown method: {request.method}",
                )

        except Exception as e:
            self.logger.error(f"Error processing request: {e}", exc_info=True)
            return MCPResponse.make_error(
                request.request_id,
                ErrorCode.INTERNAL_ERROR,
                f"Internal error: {str(e)}",
                {"exception_type": type(e).__name__, "method": request.method},
            )

    def _authenticate(self, request: MCPRequest) -> bool:
        """Authenticate request"""
        # Only require authentication if an API key is actually set
        expected_key = self.config.get("api_key")
        if not expected_key:
            return True

        # If API key is set, require authentication
        return request.auth_token == expected_key

    async def _handle_initialize(self, request: MCPRequest) -> MCPResponse:
        """Handle MCP initialize"""
        return MCPResponse.success(
            request.request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mojo-assistant", "version": "1.0.0"},
            },
        )

    async def _handle_tools_list(self, request: MCPRequest) -> MCPResponse:
        """Handle tools/list. Set MOJO_LEAN_MCP=1 for compact schemas (fixes 413 errors)."""
        import os
        if os.environ.get("MOJO_LEAN_MCP", "").strip() == "1":
            tools = self.tool_registry.get_tools_lean()
        else:
            tools = self.tool_registry.get_tools()
        return MCPResponse.success(request.request_id, {"tools": tools})

    async def _handle_tool_call(self, request: MCPRequest) -> MCPResponse:
        """Handle tools/call"""
        tool_name = request.params.get("name")
        arguments = request.params.get("arguments", {})

        if not tool_name:
            return MCPResponse.make_error(
                request.request_id,
                ErrorCode.INVALID_PARAMS,
                "Tool name required in params",
            )

        try:
            result = await self.tool_registry.execute(tool_name, arguments)

            import json

            return MCPResponse.success(
                request.request_id,
                {"content": [{"type": "text", "text": json.dumps(result)}]},
            )

        except ValueError as e:
            return MCPResponse.make_error(
                request.request_id,
                ErrorCode.METHOD_NOT_FOUND,
                f"Unknown tool: {tool_name}",
            )

        except Exception as e:
            self.logger.error(f"Tool execution error: {e}", exc_info=True)
            return MCPResponse.make_error(
                request.request_id,
                ErrorCode.TOOL_ERROR,
                f"Tool execution failed: {str(e)}",
                {"tool": tool_name, "exception": type(e).__name__},
            )
