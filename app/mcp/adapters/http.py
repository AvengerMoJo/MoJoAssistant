"""
HTTP Protocol Adapter for Web/Mobile clients
File: app/mcp/adapters/http.py
"""
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional
from app.mcp.adapters.base import ProtocolAdapter
from app.mcp.core.models import MCPRequest, MCPResponse


class HTTPAdapter(ProtocolAdapter):
    """HTTP protocol adapter using FastAPI"""
    
    def __init__(self, engine, config: Dict[str, Any]):
        self.engine = engine
        self.config = config
        self.app = None
        self.logger = None
    
    def set_logger(self, logger):
        self.logger = logger
    
    def create_app(self):
        """Create FastAPI application"""
        from fastapi import FastAPI, Request, Header, Depends
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse
        
        app = FastAPI(
            title="MoJoAssistant MCP Server",
            version="1.0.0",
            description="Unified MCP Server for memory and knowledge management"
        )
        
        cors_origins = self.config.get('cors_origins', ['http://localhost:3000'])
        if isinstance(cors_origins, str):
            cors_origins = [o.strip() for o in cors_origins.split(',')]
        
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
            max_age=3600
        )
        
        async def extract_auth_token(
            mcp_api_key: Optional[str] = Header(None, alias="MCP-API-Key"),
            x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
            authorization: Optional[str] = Header(None)
        ) -> Optional[str]:
            token = mcp_api_key or x_api_key
            if not token and authorization:
                if authorization.startswith("Bearer ") or authorization.startswith("bearer "):
                    token = authorization[7:]
            return token
        
        @app.post("/")
        async def handle_mcp_request(
            raw_request: Request,
            auth_token: Optional[str] = Depends(extract_auth_token)
        ):
            try:
                body = await raw_request.json()
                
                mcp_request = MCPRequest(
                    method=body.get("method", ""),
                    params=body.get("params", {}),
                    request_id=body.get("id"),
                    auth_token=auth_token
                )
                
                if self.logger:
                    self.logger.debug(f"HTTP received: {mcp_request.method} (id={mcp_request.request_id})")
                
                mcp_response = await self.engine.process_request(mcp_request)
                
                if mcp_response is None:
                    return JSONResponse(content={}, status_code=202)
                
                return JSONResponse(content=mcp_response.to_dict())
            
            except json.JSONDecodeError as e:
                if self.logger:
                    self.logger.error(f"JSON decode error: {e}")
                return JSONResponse(
                    content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                    status_code=400
                )
            except Exception as e:
                if self.logger:
                    self.logger.error(f"HTTP request error: {e}", exc_info=True)
                return JSONResponse(
                    content={"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "Internal error"}},
                    status_code=500
                )
        
        @app.get("/health")
        async def health_check():
            uptime = time.time() - self.engine.start_time
            return {
                "status": "healthy",
                "uptime_seconds": round(uptime, 2),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "version": "1.0.0"
            }
        
        @app.get("/info")
        async def server_info():
            tools_count = len(self.engine.tool_registry.get_tools()) if self.engine.tool_registry else 0
            return {
                "name": "MoJoAssistant MCP Server",
                "version": "1.0.0",
                "protocol": "MCP (Model Context Protocol)",
                "modes": ["stdio", "http"],
                "tools_count": tools_count
            }
        
        self.app = app
        return app
    
    async def receive_request(self) -> Optional[MCPRequest]:
        raise NotImplementedError("HTTP adapter uses FastAPI for request handling")
    
    async def send_response(self, response: MCPResponse):
        raise NotImplementedError("HTTP adapter uses FastAPI for response handling")
    
    async def run(self, host: str = "0.0.0.0", port: int = 8000):
        """Run HTTP server"""
        import uvicorn
        
        if not self.app:
            self.create_app()
        
        if self.logger:
            self.logger.info(f"Starting HTTP server on {host}:{port}")
        
        config = uvicorn.Config(self.app, host=host, port=port, log_level="info", access_log=True)
        server = uvicorn.Server(config)
        
        try:
            await server.serve()
        except Exception as e:
            if self.logger:
                self.logger.error(f"HTTP server error: {e}", exc_info=True)
            raise
