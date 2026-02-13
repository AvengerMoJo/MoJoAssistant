#!/bin/bash
# MoJoAssistant MCP Server Launcher
# Auto-generated script for easy access to MCP server

echo "Starting MoJoAssistant MCP Server..."
echo ""

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
    PYTHON_CMD=$(which python)
elif [ -d ".venv" ]; then
    source .venv/bin/activate
    PYTHON_CMD=$(which python)
else
    PYTHON_CMD=python3
    echo "No venv found, using system Python"
fi

echo "Using Python: $PYTHON_CMD"
echo ""

# Run MCP server
$PYTHON_CMD unified_mcp_server.py --mode stdio
