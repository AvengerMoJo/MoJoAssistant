#!/bin/bash
# Install MoJoAssistant MCP Server for Claude Desktop

echo "🚀 Installing MoJoAssistant MCP Server for Claude Desktop"
echo "=========================================================="

# Create directories
echo "📁 Creating directories..."
mkdir -p ~/.local/bin
mkdir -p ~/.config/Claude

# Copy MCP server
echo "📋 Installing MCP server..."
cp mcp_server.py ~/.local/bin/mojo_mcp_server.py
chmod +x ~/.local/bin/mojo_mcp_server.py

if [ -f ~/.local/bin/mojo_mcp_server.py ]; then
    echo "✅ MCP server installed: ~/.local/bin/mojo_mcp_server.py"
else
    echo "❌ Failed to install MCP server"
    exit 1
fi

# Create or update Claude Desktop configuration
echo "⚙️  Configuring Claude Desktop..."
CONFIG_FILE="$HOME/.config/Claude/claude_desktop_config.json"

if [ -f "$CONFIG_FILE" ]; then
    echo "📝 Updating existing Claude Desktop configuration..."
    # Backup existing config
    cp "$CONFIG_FILE" "$CONFIG_FILE.backup"
    echo "💾 Backup created: $CONFIG_FILE.backup"
    
    # Add MCP server to existing config (simple approach)
    python3 -c "
import json
import sys

config_file = '$CONFIG_FILE'
try:
    with open(config_file, 'r') as f:
        config = json.load(f)
except:
    config = {}

if 'mcpServers' not in config:
    config['mcpServers'] = {}

config['mcpServers']['mojo-assistant'] = {
    'command': 'python3',
    'args': ['$HOME/.local/bin/mojo_mcp_server.py']
}

with open(config_file, 'w') as f:
    json.dump(config, f, indent=2)

print('✅ Configuration updated')
"
else
    echo "📝 Creating new Claude Desktop configuration..."
    cat > "$CONFIG_FILE" << EOF
{
  "mcpServers": {
    "mojo-assistant": {
      "command": "python3",
      "args": ["$HOME/.local/bin/mojo_mcp_server.py"]
    }
  }
}
EOF
    echo "✅ Configuration created: $CONFIG_FILE"
fi

# Test MCP server
echo "🧪 Testing MCP server..."
if echo '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}' | python3 ~/.local/bin/mojo_mcp_server.py | grep -q "search_memory"; then
    echo "✅ MCP server test passed"
else
    echo "⚠️  MCP server test failed (this is OK if MCP service isn't running)"
fi

echo ""
echo "=========================================================="
echo "🎉 Installation Complete!"
echo ""
echo "📋 Next Steps:"
echo "1. Start your MCP service:"
echo "   cd $(pwd)"
echo "   python3 start_mcp_service.py"
echo "   # OR for testing: python3 simple_mcp_service.py"
echo ""
echo "2. Restart Claude Desktop application"
echo ""
echo "3. Test in Claude Desktop with these commands:"
echo "   • \"Search my memory for Python information\""
echo "   • \"Add this to my memory: I'm testing MCP integration\""
echo "   • \"What are my memory statistics?\""
echo ""
echo "✅ Claude Desktop will now have persistent memory!"
echo "🔧 Tools available: search_memory, add_knowledge, get_memory_stats"
echo ""
echo "📚 For troubleshooting, see: FINAL_CLAUDE_SETUP.md"
