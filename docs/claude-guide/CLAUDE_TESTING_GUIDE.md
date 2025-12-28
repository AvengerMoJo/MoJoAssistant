# Complete Guide: Testing MCP Service with Claude Desktop

## 🎯 Overview
This guide shows you how to connect Claude Desktop to your MoJoAssistant MCP service, enabling Claude to search your memory, add knowledge, and access your conversation history.

## ✅ Prerequisites Verified
- ✅ MCP Service is running on http://localhost:8000
- ✅ MCP Bridge is functional and tested
- ✅ All 3 tools are working: search_memory, add_knowledge, get_stats
- ✅ Claude Desktop configuration is ready

## 🚀 Step-by-Step Setup

### Step 1: Install MCP Bridge Permanently
```bash
# Copy bridge to permanent location
cp /home/alex/Development/Personal/MoJoAssistant/mcp_bridge.py ~/.local/bin/mojo_mcp_bridge.py

# Make it executable
chmod +x ~/.local/bin/mojo_mcp_bridge.py

# Test it works
echo '{"id": 1, "method": "tools/list", "params": {}}' | python3 ~/.local/bin/mojo_mcp_bridge.py
```

### Step 2: Configure Claude Desktop

**Location of config file:**
- Linux: `~/.config/Claude/claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `~/AppData/Roaming/Claude/claude_desktop_config.json`

**Configuration to add:**
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

**If config file already exists, merge with existing content:**
```json
{
  "mcpServers": {
    "existing-server": {
      "command": "existing-command"
    },
    "mojo-assistant": {
      "command": "python3", 
      "args": ["/home/alex/.local/bin/mojo_mcp_bridge.py"]
    }
  }
}
```

### Step 3: Restart Claude Desktop
1. Completely quit Claude Desktop application
2. Restart Claude Desktop
3. Look for MCP server connection in logs/status

### Step 4: Verify Tools are Available
In Claude Desktop, the following tools should now be available:
- **search_memory**: Search MoJoAssistant's memory for relevant context
- **add_knowledge**: Add information to MoJoAssistant's memory
- **get_stats**: Get memory statistics

## 🧪 Testing Commands

### Basic Functionality Tests
Try these commands in Claude Desktop:

1. **Test Memory Search:**
   ```
   "Search my memory for information about Python programming"
   ```
   *Expected: Claude should search your MoJoAssistant memory and return relevant results*

2. **Test Knowledge Addition:**
   ```
   "Remember this: FastAPI is a modern, fast web framework for building APIs with Python"
   ```
   *Expected: Claude should add this information to your memory*

3. **Test Statistics:**
   ```
   "What are my current memory statistics?"
   ```
   *Expected: Claude should show working memory, knowledge base size, etc.*

### Advanced Testing
4. **Test Search After Addition:**
   ```
   "Now search my memory for information about FastAPI"
   ```
   *Expected: Should find the FastAPI information you just added*

5. **Test Complex Queries:**
   ```
   "Search for anything related to web development or APIs"
   ```
   *Expected: Should return relevant web development information*

6. **Test Memory Persistence:**
   ```
   "Add this knowledge: MCP (Model Context Protocol) enables AI assistants to connect to external data sources and tools"
   ```
   Then: `"Search for information about MCP"`
   *Expected: Should find the MCP information*

## 🔍 Troubleshooting

### Tools Not Appearing
1. **Check Claude Desktop logs** (usually in app settings or console)
2. **Verify MCP service is running:**
   ```bash
   curl http://localhost:8000/health
   ```
3. **Test bridge manually:**
   ```bash
   echo '{"id": 1, "method": "tools/list", "params": {}}' | python3 ~/.local/bin/mojo_mcp_bridge.py
   ```

### Connection Errors
1. **Ensure MCP service is accessible:**
   ```bash
   curl http://localhost:8000/api/v1/memory/stats
   ```
2. **Check firewall settings** (port 8000 should be open)
3. **Verify bridge script permissions:**
   ```bash
   ls -la ~/.local/bin/mojo_mcp_bridge.py
   ```

### JSON Configuration Errors
1. **Validate JSON syntax** using online JSON validator
2. **Check file permissions** on config file
3. **Restart Claude Desktop** after config changes

### Bridge Script Issues
1. **Test Python path:**
   ```bash
   which python3
   ```
2. **Test requests library:**
   ```bash
   python3 -c "import requests; print('OK')"
   ```
3. **Check MCP service logs** for connection attempts

## 📊 Expected Results

### Successful Integration Signs
- ✅ Claude Desktop shows MCP server as connected
- ✅ Three new tools appear in Claude's capabilities
- ✅ Memory searches return relevant results
- ✅ Knowledge addition confirms success
- ✅ Statistics show current memory state

### What Claude Should Be Able to Do
1. **Search Your Memory**: Find information from previous conversations
2. **Add Knowledge**: Store new information for future reference
3. **Access Statistics**: Show memory usage and system status
4. **Persistent Memory**: Information added in one session available in future sessions
5. **Contextual Responses**: Use your memory to provide more relevant answers

## 🎯 Real-World Testing Scenarios

### Scenario 1: Learning Session
1. Ask Claude: "Remember that I'm learning Python web development"
2. Ask Claude: "What do you know about my learning goals?"
3. Expected: Claude should remember and reference your learning focus

### Scenario 2: Project Information
1. Tell Claude: "I'm working on a project called MoJoAssistant that uses FastAPI"
2. Later ask: "What projects am I working on?"
3. Expected: Claude should recall your project information

### Scenario 3: Technical Knowledge
1. Ask Claude: "Search my memory for any API-related information"
2. Add knowledge: "REST APIs should use proper HTTP status codes"
3. Search again: "What do I know about API best practices?"
4. Expected: Claude should find and build upon your knowledge

## 🔧 Advanced Configuration

### Custom Tool Names
You can modify the bridge script to customize tool names:
```python
# In mcp_bridge.py, change tool names:
"name": "search_mojo_memory",  # instead of "search_memory"
"name": "add_to_mojo",        # instead of "add_knowledge"
```

### Enhanced Error Handling
The bridge includes error handling for:
- MCP service unavailable
- Network timeouts
- Invalid JSON responses
- Missing parameters

### Logging
Add logging to bridge script for debugging:
```python
import logging
logging.basicConfig(level=logging.DEBUG, filename='/tmp/mcp_bridge.log')
```

## 🎉 Success Indicators

You'll know the integration is working when:
1. **Claude mentions using tools** like "Let me search your memory..."
2. **Relevant results appear** from your actual conversation history
3. **New information persists** across Claude Desktop sessions
4. **Statistics reflect changes** when you add knowledge
5. **Claude references your memory** in contextual responses

## 📞 Support

If you encounter issues:
1. Check the MCP service logs: `.memory/logs/mojo_assistant_*.log`
2. Test the bridge manually with the commands above
3. Verify Claude Desktop MCP server status
4. Ensure all file permissions are correct

The integration transforms Claude Desktop from a stateless assistant into one with persistent memory of your conversations and knowledge!
