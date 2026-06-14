"""HITL adapter package.

Importing this package registers all built-in adapter types with HITLManager.
"""

from app.mcp.adapters.hitl.base import HITLAdapter
from app.mcp.adapters.hitl.discord import DiscordHITLAdapter
from app.mcp.adapters.hitl.manager import HITLManager, _ADAPTER_REGISTRY

_ADAPTER_REGISTRY[DiscordHITLAdapter.adapter_type] = DiscordHITLAdapter

__all__ = ["HITLAdapter", "DiscordHITLAdapter", "HITLManager"]
