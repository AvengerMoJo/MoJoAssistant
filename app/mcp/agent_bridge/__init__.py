"""MCP agent bridge — Streamable-HTTP proxy between MCP clients and OpenCode servers.

Allows third-party MCP clients (Claude Desktop, Cursor, etc.) to drive
MoJoAssistant's managed OpenCode instances.  Auth: the bridge itself has a
BasicAuth password; behind it, one shared OpenCode password per host.

Config: ~/.memory/config/agent_bridge.json
"""
