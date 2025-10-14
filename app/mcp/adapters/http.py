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
    
    def _format_uptime(self, uptime_seconds: float) -> str:
        """Format uptime in human readable format"""
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    
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
                # Log request details for debugging
                content_type = raw_request.headers.get("content-type", "")
                user_agent = raw_request.headers.get("user-agent", "")
                
                if self.logger:
                    self.logger.debug(f"HTTP Request: {raw_request.method} {raw_request.url}")
                    self.logger.debug(f"Content-Type: {content_type}")
                    self.logger.debug(f"User-Agent: {user_agent}")
                
                body = await raw_request.json()
                
                # Validate JSON-RPC 2.0 format
                if not isinstance(body, dict):
                    return JSONResponse(
                        content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request - body must be object"}},
                        status_code=400
                    )
                
                if "jsonrpc" not in body or body.get("jsonrpc") != "2.0":
                    return JSONResponse(
                        content={"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32600, "message": "Invalid Request - missing or invalid jsonrpc version"}},
                        status_code=400
                    )
                
                if "method" not in body:
                    return JSONResponse(
                        content={"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32600, "message": "Invalid Request - missing method"}},
                        status_code=400
                    )
                
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
                    self.logger.warning(f"Invalid JSON in request body: {e}")
                return JSONResponse(
                    content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error - invalid JSON"}},
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
        
        # Legacy REST endpoints for direct HTTP access
        @app.post("/api/v1/memory/context")
        async def get_memory_context_rest(query_data: Dict[str, Any], auth_token: Optional[str] = Depends(extract_auth_token)):
            result = await self.engine.tool_registry.execute("get_memory_context", query_data)
            if isinstance(result, dict) and "status" in result and result["status"] == "placeholder":
                raise HTTPException(status_code=501, detail="Tool not implemented")
            return result
        
        @app.get("/api/v1/memory/stats")
        async def get_memory_stats_rest(auth_token: Optional[str] = Depends(extract_auth_token)):
            result = await self.engine.tool_registry.execute("get_memory_stats", {})
            if isinstance(result, dict) and "status" in result and result["status"] == "placeholder":
                raise HTTPException(status_code=501, detail="Tool not implemented")
            return result
        
        # System endpoints
        @app.get("/system/info")
        async def system_info_rest(auth_token: Optional[str] = Depends(extract_auth_token)):
            # System info is not implemented, return basic info
            uptime = time.time() - self.engine.start_time
            return {
                "server_name": "mojo-assistant",
                "version": "1.0.0",
                "uptime_seconds": uptime,
                "uptime_formatted": self._format_uptime(uptime),
                "memory_service": "initialized" if hasattr(self.engine, 'memory_service') else "not_initialized",
                "tools_count": len(self.engine.tool_registry.get_tools()) if self.engine.tool_registry else 0
            }
        
        @app.get("/system/health")
        async def system_health_rest(auth_token: Optional[str] = Depends(extract_auth_token)):
            # System health is not implemented, return basic health
            return {
                "status": "healthy",
                "uptime_seconds": round(time.time() - self.engine.start_time, 2),
                "tools_available": len(self.engine.tool_registry.get_tools()) if self.engine.tool_registry else 0,
                "timestamp": time.time()
            }
        
        # Additional endpoints for the client
        @app.post("/api/v1/knowledge/documents")
        async def add_documents_rest(documents_data: Dict[str, Any], auth_token: Optional[str] = Depends(extract_auth_token)):
            result = await self.engine.tool_registry.execute("add_documents", documents_data)
            if isinstance(result, dict) and "status" in result and result["status"] == "placeholder":
                raise HTTPException(status_code=501, detail="Tool not implemented")
            return result
        
        @app.get("/api/v1/knowledge/documents")
        async def list_documents_rest(limit: int = 50, offset: int = 0, search: Optional[str] = None, auth_token: Optional[str] = Depends(extract_auth_token)):
            # This endpoint doesn't have a corresponding tool, return placeholder
            raise HTTPException(status_code=501, detail="Endpoint not implemented")
        
        @app.post("/api/v1/conversation/message")
        async def add_message_rest(message_data: Dict[str, Any], auth_token: Optional[str] = Depends(extract_auth_token)):
            # Map to add_conversation tool
            messages = [{
                "type": message_data.get("type"),
                "content": message_data.get("content")
            }]
            result = await self.engine.tool_registry.execute("add_conversation", {"messages": messages})
            if isinstance(result, dict) and "status" in result and result["status"] == "placeholder":
                raise HTTPException(status_code=501, detail="Tool not implemented")
            return result
        
        @app.post("/api/v1/conversation/end")
        async def end_conversation_rest(auth_token: Optional[str] = Depends(extract_auth_token)):
            result = await self.engine.tool_registry.execute("end_conversation", {})
            if isinstance(result, dict) and "status" in result and result["status"] == "placeholder":
                raise HTTPException(status_code=501, detail="Tool not implemented")
            return result
        
        @app.get("/api/v1/conversation/current")
        async def get_current_conversation_rest(auth_token: Optional[str] = Depends(extract_auth_token)):
            # This endpoint doesn't have a corresponding tool, return placeholder
            raise HTTPException(status_code=501, detail="Endpoint not implemented")
        
        @app.get("/api/v1/embeddings/models")
        async def list_embedding_models_rest(auth_token: Optional[str] = Depends(extract_auth_token)):
            # This endpoint doesn't have a corresponding tool, return placeholder
            raise HTTPException(status_code=501, detail="Endpoint not implemented")
        
        @app.post("/api/v1/embeddings/switch")
        async def switch_embedding_model_rest(model_data: Dict[str, Any], auth_token: Optional[str] = Depends(extract_auth_token)):
            # This endpoint doesn't have a corresponding tool, return placeholder
            raise HTTPException(status_code=501, detail="Endpoint not implemented")
        
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
            self.app = self.create_app()
        
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
