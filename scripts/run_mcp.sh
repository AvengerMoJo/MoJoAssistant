#!/bin/bash
# MoJoAssistant MCP Server Launcher
# Starts the MCP server in STDIO mode for Claude Desktop integration

set -e  # Exit on error

# Get project root (one level up from scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  MoJoAssistant MCP Server${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${RED}✗ Virtual environment not found!${NC}"
    echo -e "  Please run: python3 install.py"
    exit 1
fi

# Activate virtual environment
echo -e "${GREEN}✓ Activating virtual environment${NC}"
source venv/bin/activate

# Check if unified_mcp_server.py exists
if [ ! -f "unified_mcp_server.py" ]; then
    echo -e "${RED}✗ unified_mcp_server.py not found!${NC}"
    echo -e "  Are you in the MoJoAssistant directory?"
    exit 1
fi

# Check configuration
if [ ! -f "config/llm_config.json" ]; then
    echo -e "${YELLOW}⚠ LLM configuration not found${NC}"
    echo -e "  Creating default configuration..."
    mkdir -p config
    python -c "
import json
config = {
    'local_models': {
        'qwen-coder-small': {
            'type': 'llama',
            'path': '~/.cache/mojoassistant/models/qwen2.5-coder-1.5b-instruct-q5_k_m.gguf',
            'context_length': 32768
        }
    },
    'default_interface': 'qwen-coder-small'
}
with open('config/llm_config.json', 'w') as f:
    json.dump(config, f, indent=2)
"
    echo -e "${GREEN}✓ Configuration created${NC}"
fi

# Start server
echo -e "${GREEN}✓ Starting MCP server in STDIO mode${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

exec python unified_mcp_server.py --mode stdio
