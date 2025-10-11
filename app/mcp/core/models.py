"""
Core data models for MCP protocol
File: app/mcp/core/models.py
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Union
from enum import Enum


class ErrorCode(Enum):
    """Standard JSON-RPC 2.0 error codes"""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    SERVER_ERROR = -32000
    TOOL_ERROR = -32001
    AUTH_ERROR = -32002


@dataclass
class MCPRequest:
    """Unified request representation"""
    method: str
    params: Dict[str, Any]
    request_id: Optional[Union[str, int]] = None
    auth_token: Optional[str] = None
    
    def is_notification(self) -> bool:
        """Check if this is a notification (no response expected)"""
        return self.request_id is None


@dataclass
class MCPResponse:
    """Unified response representation"""
    request_id: Optional[Union[str, int]]
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-RPC 2.0 format"""
        response = {"jsonrpc": "2.0", "id": self.request_id}
        if self.error is not None:
            response["error"] = self.error
        else:
            response["result"] = self.result
        return response
    
    @classmethod
    def success(cls, request_id: Any, result: Any) -> 'MCPResponse':
        """Create success response"""
        return cls(request_id=request_id, result=result, error=None)
    
    @classmethod
    def make_error(cls, request_id: Any, code: ErrorCode, message: str, data: Any = None) -> 'MCPResponse':
        """Create error response"""
        error_dict = {
            "code": code.value,
            "message": message
        }
        if data is not None:
            error_dict["data"] = data
        return cls(request_id=request_id, result=None, error=error_dict)
