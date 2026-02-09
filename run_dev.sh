#!/bin/bash
# Development server with hot reload
# Usage: ./run_dev.sh

# Activate venv if it exists
if [ -f "./venv/bin/activate" ]; then
    source ./venv/bin/activate
fi

echo "Starting development server with hot reload..."
echo "Edit any file in ./app/ and it will auto-reload"
echo ""

# Use the existing unified_mcp_server.py with --reload flag
python3 unified_mcp_server.py --mode http --port 8000 --reload
