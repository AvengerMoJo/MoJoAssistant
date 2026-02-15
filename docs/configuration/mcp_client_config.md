# MCP Client Configuration

## Claude Desktop Configuration

Add to your Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcp": {
    "mojo-assistant": {
      "command": "python",
      "args": ["/path/to/unified_mcp_server.py", "--mode", "stdio"]
    }
  }
}
```

## Android/Remote Configuration  

For Android or other remote clients:

```json
{
  "mcp": {
    "mojo-assistant": {
      "type": "remote",
      "url": "https://your-server:8000",
      "headers": {
        "MCP-API-Key": "your-api-key-here"
      },
      "enabled": true
    }
  }
}
```

## Server Deployment

### STDIO Mode (Claude Desktop)
```bash
export MCP_API_KEY=your-backend-api-key
python unified_mcp_server.py --mode stdio
```

### HTTP Mode (Android/Web)
```bash
export MCP_API_KEY=your-backend-api-key
python unified_mcp_server.py --mode http --host 0.0.0.0 --port 8000
```

### Optional: Disable Authentication (Development)
```bash
export MCP_REQUIRE_AUTH=false
python unified_mcp_server.py --mode http
```

## Available Tools

- `get_memory_context` - Search all memory tiers (working, active, archival, knowledge base)
- `add_documents` - Add documents to knowledge base
- `get_memory_stats` - Get memory system statistics
- `end_conversation` - Archive conversation to memory