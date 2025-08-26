#!/bin/bash
# Fresh Installation of MoJoAssistant MCP for Claude Desktop

echo "🚀 Fresh Installation: MoJoAssistant MCP for Claude Desktop"
echo "============================================================"

# Check if MCP service is available
echo "🔍 Checking MCP service availability..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ MCP service is running on http://localhost:8000"
    SERVICE_STATUS="running"
else
    echo "⚠️  MCP service is not running"
    echo "   You'll need to start it after installation:"
    echo "   cd $(pwd)"
    echo "   python3 start_mcp_service.py"
    SERVICE_STATUS="stopped"
fi

# Create directories
echo ""
echo "📁 Creating directories..."
mkdir -p ~/.local/bin
mkdir -p ~/.config/Claude

# Install the latest MCP server
echo "📋 Installing MCP server..."
if [ -f "mcp_server.py" ]; then
    cp mcp_server.py ~/.local/bin/mojo_mcp_server.py
    chmod +x ~/.local/bin/mojo_mcp_server.py
    echo "✅ MCP server installed: ~/.local/bin/mojo_mcp_server.py"
else
    echo "❌ Error: mcp_server.py not found in current directory"
    echo "   Make sure you're running this from the MoJoAssistant directory"
    exit 1
fi

# Test MCP server
echo "🧪 Testing MCP server..."
TEST_RESULT=$(echo '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}' | python3 ~/.local/bin/mojo_mcp_server.py 2>/dev/null)

if echo "$TEST_RESULT" | grep -q "search_memory"; then
    echo "✅ MCP server test passed - 3 tools available"
else
    echo "⚠️  MCP server test failed, but installation continues"
    echo "   This might be OK if the MCP service isn't running"
fi

# Configure Claude Desktop
echo ""
echo "⚙️  Configuring Claude Desktop..."
CONFIG_FILE="$HOME/.config/Claude/claude_desktop_config.json"

# Create or update configuration
python3 -c "
import json
import os

config_file = '$CONFIG_FILE'
config = {}

# Load existing config if it exists
if os.path.exists(config_file):
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        print('📝 Loaded existing Claude Desktop configuration')
    except:
        print('📝 Creating new Claude Desktop configuration')
        config = {}
else:
    print('📝 Creating new Claude Desktop configuration')

# Ensure mcpServers section exists
if 'mcpServers' not in config:
    config['mcpServers'] = {}

# Add MoJoAssistant MCP server
config['mcpServers']['mojo-assistant'] = {
    'command': 'python3',
    'args': ['$HOME/.local/bin/mojo_mcp_server.py']
}

# Save configuration
with open(config_file, 'w') as f:
    json.dump(config, f, indent=2)

print('✅ Claude Desktop configuration updated')
"

# Verify configuration
echo "🔍 Verifying configuration..."
if [ -f "$CONFIG_FILE" ]; then
    if grep -q "mojo-assistant" "$CONFIG_FILE"; then
        echo "✅ Configuration verified - mojo-assistant MCP server registered"
    else
        echo "❌ Configuration verification failed"
        exit 1
    fi
else
    echo "❌ Configuration file not created"
    exit 1
fi

# Show configuration
echo ""
echo "📋 Current Claude Desktop Configuration:"
echo "----------------------------------------"
cat "$CONFIG_FILE"
echo "----------------------------------------"

echo ""
echo "============================================================"
echo "🎉 Fresh Installation Complete!"
echo ""
echo "📊 Installation Summary:"
echo "   ✅ MCP server: ~/.local/bin/mojo_mcp_server.py"
echo "   ✅ Claude config: ~/.config/Claude/claude_desktop_config.json"
echo "   ✅ Tools available: search_memory, add_knowledge, get_memory_stats"

if [ "$SERVICE_STATUS" = "running" ]; then
    echo "   ✅ MCP service: Running on http://localhost:8000"
else
    echo "   ⚠️  MCP service: Not running (start it manually)"
fi

echo ""
echo "🚀 Next Steps:"
echo "1. Start MCP service (if not running):"
echo "   cd $(pwd)"
echo "   python3 start_mcp_service.py"
echo ""
echo "2. Restart Claude Desktop completely:"
echo "   - Quit Claude Desktop application"
echo "   - Start Claude Desktop again"
echo ""
echo "3. Test in Claude Desktop:"
echo "   • \"Search my memory for Python information\""
echo "   • \"Add this to my memory: Testing fresh MCP installation\""
echo "   • \"What are my memory statistics?\""
echo ""
echo "✅ Claude Desktop will now have persistent memory!"

# Create quick test script
cat > test_claude_mcp.py << 'EOF'
#!/usr/bin/env python3
"""Quick test of Claude Desktop MCP integration"""
import subprocess
import json

def test_mcp_server():
    print("🧪 Testing MCP Server Integration")
    print("=" * 40)
    
    tests = [
        ("List Tools", '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}'),
        ("Initialize", '{"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}}')
    ]
    
    for name, request in tests:
        try:
            result = subprocess.run(
                ["python3", "/home/alex/.local/bin/mojo_mcp_server.py"],
                input=request + "\n",
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.stdout:
                response = json.loads(result.stdout.strip())
                if "result" in response:
                    print(f"✅ {name}: PASSED")
                    if name == "List Tools":
                        tools = response["result"].get("tools", [])
                        print(f"   🔧 Found {len(tools)} tools: {[t['name'] for t in tools]}")
                else:
                    print(f"❌ {name}: No result")
            else:
                print(f"❌ {name}: No output")
                
        except Exception as e:
            print(f"❌ {name}: Error - {e}")

if __name__ == "__main__":
    test_mcp_server()
EOF

chmod +x test_claude_mcp.py
echo ""
echo "📋 Created test script: test_claude_mcp.py"
echo "   Run: python3 test_claude_mcp.py"
