"""
STDIO Protocol Adapter for Claude Desktop
File: app/mcp/adapters/stdio.py
"""
import sys
import json
from typing import Optional
from app.mcp.adapters.base import ProtocolAdapter
from app.mcp.core.models import MCPRequest, MCPResponse


class STDIOAdapter(ProtocolAdapter):
    """STDIO protocol adapter for Claude Desktop integration"""
    
    def __init__(self):
        self.logger = None
    
    def set_logger(self, logger):
        self.logger = logger
    
    async def receive_request(self) -> Optional[MCPRequest]:
        """Read JSON-RPC request from stdin"""
        try:
            line = sys.stdin.readline()
            
            if not line:
                if self.logger:
                    self.logger.info("STDIO input stream closed")
                return None
            
            line = line.strip()
            if not line:
                return await self.receive_request()
            
            data = json.loads(line)
            
            if self.logger:
                self.logger.debug(f"STDIO received: {data}")
            
            return MCPRequest(
                method=data.get("method", ""),
                params=data.get("params", {}),
                request_id=data.get("id"),
                auth_token=None
            )
        
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.error(f"JSON decode error: {e}")
            return MCPRequest(
                method="__parse_error__",
                params={"error": str(e)},
                request_id=None
            )
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error receiving STDIO request: {e}", exc_info=True)
            return None
    
    async def send_response(self, response: Optional[MCPResponse]):
        """Write JSON-RPC response to stdout"""
        if response is None:
            return
        
        try:
            output = json.dumps(response.to_dict())
            print(output)
            sys.stdout.flush()
            
            if self.logger:
                self.logger.debug(f"STDIO sent: {output}")
        
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error sending STDIO response: {e}", exc_info=True)
