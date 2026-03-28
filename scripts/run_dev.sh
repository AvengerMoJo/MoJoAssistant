#!/bin/bash
# Development server with hot reload
# Usage: ./run_dev.sh

# Activate venv if it exists
if [ -f "$(dirname "$0")/../venv/bin/activate" ]; then
    source "$(dirname "$0")/../venv/bin/activate"
fi

echo "Starting development server with hot reload..."
echo "Edit any file in ./app/ and it will auto-reload"
echo ""

# Use the existing unified_mcp_server.py with --reload flag
python3 "$(dirname "$0")/../unified_mcp_server.py" --mode http --port 8000 --reload
