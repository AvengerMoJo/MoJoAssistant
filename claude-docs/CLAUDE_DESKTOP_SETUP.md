
# Claude Desktop MCP Integration Instructions

## Step 1: Ensure MCP Service is Running
```bash
cd /home/alex/Development/Personal/MoJoAssistant
python3 start_mcp_service.py
```

## Step 2: Configure Claude Desktop

### Option A: Using MCP Bridge (Recommended)
1. Copy the MCP bridge script to a permanent location:
   ```bash
   cp mcp_bridge.py ~/.local/bin/mojo_mcp_bridge.py
   chmod +x ~/.local/bin/mojo_mcp_bridge.py
   ```

2. Add to Claude Desktop configuration (~/.config/Claude/claude_desktop_config.json):
   ```json
   {
     "mcpServers": {
       "mojo-assistant": {
         "command": "python3",
         "args": ["/home/alex/.local/bin/mojo_mcp_bridge.py"]
       }
     }
   }
   ```

### Option B: Direct HTTP Integration
Add this to Claude Desktop config:
```json
{
  "mcpServers": {
    "mojo-assistant": {
      "command": "curl",
      "args": ["-X", "POST", "http://localhost:8000/api/v1/memory/context", 
               "-H", "Content-Type: application/json",
               "-d", "{\"query\": \"$1\", \"max_items\": 5}"]
    }
  }
}
```

## Step 3: Test Integration

1. Restart Claude Desktop
2. In a conversation, try:
   - "Search my memory for information about Python"
   - "Add this knowledge: FastAPI is a modern web framework"
   - "Show me my memory statistics"

## Step 4: Verify Tools are Available

Claude should now have access to these tools:
- **search_memory**: Search MoJoAssistant's memory
- **add_knowledge**: Add information to memory
- **get_stats**: Get memory statistics

## Troubleshooting

1. **Tools not appearing**: Check Claude Desktop logs
2. **Connection errors**: Ensure MCP service is running on port 8000
3. **Permission errors**: Check file permissions on bridge script
4. **JSON errors**: Validate configuration file syntax

## Testing Commands

Try these in Claude Desktop:
- "What do you know about machine learning?" (should search memory)
- "Remember that Python is great for AI development" (should add to memory)
- "How much information do you have stored?" (should show stats)
