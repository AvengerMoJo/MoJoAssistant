"""
Main Unified MCP Server orchestrator
File: app/mcp/server.py
"""
import os
from typing import Dict, Any
from app.mcp.core.engine import MCPEngine
from app.mcp.adapters.stdio import STDIOAdapter
from app.mcp.adapters.http import HTTPAdapter


class UnifiedMCPServer:
    """Main server orchestrator"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or self._load_config()
        self.engine = MCPEngine(config=self.config)
        self.logger = None
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from environment variables"""
        return {
            'require_auth': os.getenv("MCP_REQUIRE_AUTH", "true").lower() == "true",
            'api_key': os.getenv("MCP_API_KEY"),
            'cors_origins': os.getenv("MCP_CORS_ORIGINS", "http://localhost:3000"),
            'log_level': os.getenv("LOG_LEVEL", "INFO"),
        }
    
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
    
    async def run_http(self, host: str = "0.0.0.0", port: int = 8000):
        """Run server in HTTP mode (for Web/Mobile)"""
        await self.engine.initialize()
        self.logger = self.engine.logger
        
        adapter = HTTPAdapter(self.engine, self.config)
        adapter.set_logger(self.logger)
        
        self.logger.info(f"MCP Server starting in HTTP mode on {host}:{port}")
        
        try:
            await adapter.run(host, port)
        except Exception as e:
            self.logger.error(f"HTTP server error: {e}", exc_info=True)
            raise
