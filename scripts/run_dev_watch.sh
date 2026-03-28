#!/bin/bash
# Development server with auto-reload using watchfiles
# Usage: ./run_dev_watch.sh

# Activate venv if it exists
if [ -f "$(dirname "$0")/../venv/bin/activate" ]; then
    source "$(dirname "$0")/../venv/bin/activate"
fi

# Check if watchfiles is installed
if ! python3 -c "import watchfiles" 2>/dev/null; then
    echo "⚠️  watchfiles not installed"
    echo ""
    echo "Install with: pip install watchfiles"
    echo ""
    exit 1
fi

echo "🔥 Starting development server with auto-reload (watchfiles)"
echo "📝 Edit any .py file in ./app/ to trigger restart"
echo ""

# Use watchfiles to watch for changes and restart server
watchfiles --filter python \
  'python3 "$(dirname "$0")/../unified_mcp_server.py" --mode http --port 8000' \
  app/
