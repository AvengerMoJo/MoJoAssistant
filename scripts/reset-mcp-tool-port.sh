#!/bin/bash
# Reset global MCP tool port to 3005

set -e

STATE_FILE="$HOME/.memory/opencode-state.json"

echo "🔧 Resetting global MCP tool port to 3005..."

# Check if state file exists
if [ ! -f "$STATE_FILE" ]; then
    echo "❌ State file not found at $STATE_FILE"
    exit 1
fi

# Backup state file
BACKUP_FILE="$STATE_FILE.backup.$(date +%Y%m%d_%H%M%S)"
echo "📦 Backing up state to $BACKUP_FILE"
cp "$STATE_FILE" "$BACKUP_FILE"

# Check if jq is available
if ! command -v jq &> /dev/null; then
    echo "❌ jq is required but not installed"
    echo "   Install with: sudo apt install jq"
    exit 1
fi

# Get current port and PID
CURRENT_PORT=$(jq -r '.global_mcp_tool.port // "null"' "$STATE_FILE")
CURRENT_PID=$(jq -r '.global_mcp_tool.pid // "null"' "$STATE_FILE")

echo "📊 Current state:"
echo "   Port: $CURRENT_PORT"
echo "   PID: $CURRENT_PID"

# Kill the process if running
if [ "$CURRENT_PID" != "null" ] && [ "$CURRENT_PID" != "" ]; then
    if ps -p "$CURRENT_PID" > /dev/null 2>&1; then
        echo "🛑 Stopping global MCP tool (PID $CURRENT_PID)..."
        kill "$CURRENT_PID" 2>/dev/null || true
        sleep 2

        # Force kill if still running
        if ps -p "$CURRENT_PID" > /dev/null 2>&1; then
            echo "   Force killing..."
            kill -9 "$CURRENT_PID" 2>/dev/null || true
        fi

        echo "   ✓ Process stopped"
    else
        echo "   Process not running"
    fi
fi

# Update state file - set port to null so it will use default (3005)
echo "🔄 Updating state file..."
jq '.global_mcp_tool.port = null | .global_mcp_tool.pid = null | .global_mcp_tool.status = "stopped"' "$STATE_FILE" > "$STATE_FILE.tmp"
mv "$STATE_FILE.tmp" "$STATE_FILE"
chmod 600 "$STATE_FILE"

echo "✅ Port reset complete!"
echo ""
echo "Next steps:"
echo "1. Restart your MCP server (if not auto-reloading)"
echo "2. Run: opencode_restart <project_name>"
echo "3. The global MCP tool will start on port 3005"
echo ""
echo "Verify with: opencode_mcp_status"
