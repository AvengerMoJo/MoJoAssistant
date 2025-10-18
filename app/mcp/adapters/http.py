"""
HTTP Protocol Adapter for Web/Mobile clients
File: app/mcp/adapters/http.py
"""
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.mcp.adapters.base import ProtocolAdapter
from app.mcp.core.models import MCPRequest, MCPResponse


class HTTPAdapter(ProtocolAdapter):
    """Simple HTTP protocol adapter using FastAPI"""
    
    def __init__(self, engine, config: Dict[str, Any]):
        self.engine = engine
        self.config = config
        self.app = None
        self.logger = None
    
    def set_logger(self, logger):
        self.logger = logger
    
    def create_app(self):
        """Create FastAPI application"""
        app = FastAPI(
            title="MoJoAssistant MCP Server",
            version="1.0.0",
            description="Simple MCP Server for memory and knowledge management"
        )
        
        # Simple CORS
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        @app.post("/")
        async def handle_mcp_request(
            raw_request: Request,
            mcp_api_key: Optional[str] = Header(None, alias="MCP-API-Key"),
            mcp_env_api_key: Optional[str] = Header(None, alias="MCP_API_KEY")
        ):
            try:
                body = await raw_request.json()
                
                # Validate JSON-RPC 2.0 format
                if not isinstance(body, dict):
                    return JSONResponse(
                        content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}},
                        status_code=400
                    )
                
                if "jsonrpc" not in body or body.get("jsonrpc") != "2.0":
                    return JSONResponse(
                        content={"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32600, "message": "Invalid Request"}},
                        status_code=400
                    )
                
                if "method" not in body:
                    return JSONResponse(
                        content={"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32600, "message": "Invalid Request"}},
                        status_code=400
                    )
                
                mcp_request = MCPRequest(
                    method=body.get("method", ""),
                    params=body.get("params", {}),
                    request_id=body.get("id"),
                    auth_token=None
                )
                
                if self.logger:
                    self.logger.debug(f"HTTP received: {mcp_request.method}")
                
                mcp_response = await self.engine.process_request(mcp_request)
                
                if mcp_response is None:
                    return JSONResponse(content={}, status_code=202)
                
                return JSONResponse(content=mcp_response.to_dict())
            
            except json.JSONDecodeError:
                return JSONResponse(
                    content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                    status_code=400
                )
            except Exception as e:
                if self.logger:
                    self.logger.error(f"HTTP request error: {e}")
                return JSONResponse(
                    content={"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "Internal error"}},
                    status_code=500
                )
        
        @app.get("/health")
        async def health_check():
            uptime = time.time() - self.engine.start_time
            return {
                "status": "healthy",
                "uptime": round(uptime, 2)
            }
        
        self.app = app
        return app
    
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