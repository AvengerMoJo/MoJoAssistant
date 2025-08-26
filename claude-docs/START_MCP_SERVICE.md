# How to Start MCP Service for Claude Desktop

## 🚀 Quick Start

### Option 1: Full MCP Service (Recommended)
```bash
cd /home/alex/Development/Personal/MoJoAssistant
python3 start_mcp_service.py
```

**Requirements**: FastAPI and uvicorn
```bash
pip install fastapi uvicorn
```

### Option 2: Simple Test Service (No Dependencies)
```bash
cd /home/alex/Development/Personal/MoJoAssistant
python3 simple_mcp_service.py
```

**No additional requirements** - uses only Python standard library

## 🔍 Verify Service is Running

Check if the service is working:
```bash
curl http://localhost:8000/health
```

Should return:
```json
{"status": "healthy", "version": "1.0.0", ...}
```

## 🧪 Test Claude Desktop Integration

1. **Start MCP Service** (choose option 1 or 2 above)
2. **Restart Claude Desktop** completely (quit and restart)
3. **Test these commands in Claude Desktop:**
   - "Search my memory for Python information"
   - "Add this to my memory: Testing MCP integration"
   - "What are my memory statistics?"

## ✅ Success Indicators

You'll know it's working when:
- Claude mentions using tools: "Let me search your memory..."
- Memory searches return relevant information
- Added knowledge persists across sessions
- Statistics show current memory state

## 🔧 Troubleshooting

### Service Won't Start
- **Full Service**: Install dependencies with `pip install fastapi uvicorn`
- **Simple Service**: Should work with any Python 3.7+

### Claude Desktop Not Connecting
- Ensure MCP service is running on port 8000
- Restart Claude Desktop completely
- Check Claude Desktop logs for MCP connection errors

### Tools Not Appearing
- Verify Claude Desktop config: `~/.config/Claude/claude_desktop_config.json`
- Ensure MCP server path is correct: `/home/alex/.local/bin/mojo_mcp_server.py`
- Test MCP server: `python3 test_claude_mcp.py`

## 📋 Current Installation Status

✅ **MCP Server**: Installed at `~/.local/bin/mojo_mcp_server.py`  
✅ **Claude Config**: Updated at `~/.config/Claude/claude_desktop_config.json`  
✅ **Tools Available**: search_memory, add_knowledge, get_memory_stats  
⚠️  **MCP Service**: Needs to be started manually  

## 🎯 Next Steps

1. Choose and start your MCP service (Option 1 or 2)
2. Restart Claude Desktop
3. Test the integration with the commands above
4. Enjoy persistent memory in Claude Desktop!
