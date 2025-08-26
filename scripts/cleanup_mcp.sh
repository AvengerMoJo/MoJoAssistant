#!/bin/bash
# Cleanup Previous MCP Installation

echo "🧹 Cleaning Up Previous MCP Installation"
echo "========================================"

# Remove old MCP server files
echo "📁 Removing old MCP server files..."
if [ -f ~/.local/bin/mojo_mcp_server.py ]; then
    rm ~/.local/bin/mojo_mcp_server.py
    echo "✅ Removed: ~/.local/bin/mojo_mcp_server.py"
fi

if [ -f ~/.local/bin/mojo_mcp_bridge.py ]; then
    rm ~/.local/bin/mojo_mcp_bridge.py
    echo "✅ Removed: ~/.local/bin/mojo_mcp_bridge.py"
fi

# Backup and clean Claude Desktop config
echo "⚙️  Cleaning Claude Desktop configuration..."
CONFIG_FILE="$HOME/.config/Claude/claude_desktop_config.json"

if [ -f "$CONFIG_FILE" ]; then
    # Create backup with timestamp
    BACKUP_FILE="$CONFIG_FILE.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$CONFIG_FILE" "$BACKUP_FILE"
    echo "💾 Backup created: $BACKUP_FILE"
    
    # Remove mojo-assistant entries
    python3 -c "
import json
import sys

config_file = '$CONFIG_FILE'
try:
    with open(config_file, 'r') as f:
        config = json.load(f)
    
    if 'mcpServers' in config and 'mojo-assistant' in config['mcpServers']:
        del config['mcpServers']['mojo-assistant']
        print('🗑️  Removed mojo-assistant MCP server entry')
        
        # If mcpServers is now empty, remove it
        if not config['mcpServers']:
            del config['mcpServers']
            print('🗑️  Removed empty mcpServers section')
    
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)
    
    print('✅ Claude Desktop config cleaned')
    
except Exception as e:
    print(f'⚠️  Error cleaning config: {e}')
"
else
    echo "ℹ️  No Claude Desktop config found"
fi

echo ""
echo "✅ Cleanup Complete!"
echo "Ready for fresh installation."
