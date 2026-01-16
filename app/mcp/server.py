"""
Main Unified MCP Server orchestrator
File: app/mcp/server.py
"""

import os
from typing import Dict, Any
from app.config.app_config import get_app_config, AppConfig
from app.mcp.core.engine import MCPEngine
from app.mcp.adapters.stdio import STDIOAdapter
from app.mcp.adapters.http import HTTPAdapter


class UnifiedMCPServer:
    """Main server orchestrator"""

    def __init__(self, app_config: AppConfig = None):
        self.app_config = app_config or get_app_config()

        # Create full config dict for MCPEngine (includes memory settings)
        full_config = {
            "api_key": self.app_config.server.api_key,
            "cors_origins": ",".join(self.app_config.server.cors_origins),
            "log_level": self.app_config.logging.level,
            # Memory configuration
            "embedding_model": self.app_config.memory.embedding_model,
            "multi_model_enabled": self.app_config.memory.multi_model_enabled,
            "vector_store": self.app_config.memory.vector_store,
            "max_context_items": self.app_config.memory.max_context_items,
        }

        self.engine = MCPEngine(config=full_config)
        self.logger = None

    async def run_stdio(self):
        """Run server in STDIO mode (for Claude Desktop)"""
        await self.engine.initialize()
        self.logger = self.engine.logger

        adapter = STDIOAdapter()
        adapter.set_logger(self.logger)

        self.logger.info("MCP Server started in STDIO mode")

        while True:
            try:
                request = await adapter.receive_request()
                if request is None:
                    self.logger.info("STDIO input closed, shutting down")
                    break

                response = await self.engine.process_request(request)
                await adapter.send_response(response)

            except KeyboardInterrupt:
                self.logger.info("Received interrupt, shutting down")
                break
            except Exception as e:
                self.logger.error(f"Error in STDIO loop: {e}", exc_info=True)
                continue

    async def run_http(self, host: str = None, port: int = None):
        """Run server in HTTP mode (for Web/Mobile)"""
        # Use configuration values if not provided
        if host is None:
            host = self.app_config.server.host
        if port is None:
            port = self.app_config.server.port

        await self.engine.initialize()
        self.logger = self.engine.logger

        # Create legacy config for HTTPAdapter
        legacy_config = {
            "api_key": self.app_config.server.api_key,
            "cors_origins": ",".join(self.app_config.server.cors_origins),
            "log_level": self.app_config.logging.level,
        }

        adapter = HTTPAdapter(self.engine, legacy_config)
        adapter.set_logger(self.logger)

        self.logger.info(f"MCP Server starting in HTTP mode on {host}:{port}")
        self.logger.info(f"OAuth enabled: {self.app_config.oauth.enabled}")
        if self.app_config.oauth.enabled:
            self.logger.info(f"OAuth issuer: {self.app_config.oauth.issuer}")

        try:
            await adapter.run(host, port)
        except Exception as e:
            self.logger.error(f"HTTP server error: {e}", exc_info=True)
            raise
