"""
Abstract base class for protocol adapters
File: app/mcp/adapters/base.py
"""
from abc import ABC, abstractmethod
from typing import Optional
from app.mcp.core.models import MCPRequest, MCPResponse


class ProtocolAdapter(ABC):
    """Abstract base class for protocol adapters"""
    
    @abstractmethod
    async def receive_request(self) -> Optional[MCPRequest]:
        """Receive and parse a request from the protocol"""
        pass
    
    @abstractmethod
    async def send_response(self, response: Optional[MCPResponse]):
        """Send a response via the protocol"""
        pass
    
    def set_logger(self, logger):
        """Set logger for the adapter (optional)"""
        pass
