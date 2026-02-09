"""
OpenCode Manager Module

Manages lifecycle of OpenCode server instances and their associated MCP tools.
Each project runs in an isolated sandbox with its own OpenCode web server
and opencode-mcp-tool instance.

File: app/mcp/opencode/__init__.py
"""

from app.mcp.opencode.manager import OpenCodeManager

__all__ = ["OpenCodeManager"]
