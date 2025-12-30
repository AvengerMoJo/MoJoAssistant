#!/usr/bin/env python3
"""
MoJoAssistant MCP Server - Unified Architecture
Entry point for both STDIO and HTTP modes
"""
import os
import sys
import asyncio
import argparse
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import with fallbacks for different environments (uv, pip, etc.)
try:
    from dotenv import load_dotenv
except ImportError:
    # Fallback if python-dotenv is not available
    def load_dotenv(*args, **kwargs):
        pass

from app.mcp.server import UnifiedMCPServer

env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="MoJoAssistant MCP Server - Unified Architecture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # STDIO mode (Claude Desktop)
  python unified_mcp_server.py --mode stdio
  
  # HTTP mode (Web/Mobile)
  python unified_mcp_server.py --mode http --port 8000
        """
    )
    
    parser.add_argument("--mode", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    
    args = parser.parse_args()
    
    server = UnifiedMCPServer()
    
    try:
        if args.mode == "stdio":
            print("Starting MCP Server in STDIO mode", file=sys.stderr)
            asyncio.run(server.run_stdio())
        else:
            print(f"Starting MCP Server in HTTP mode on {args.host}:{args.port}", file=sys.stderr)
            asyncio.run(server.run_http(args.host, args.port))
    except KeyboardInterrupt:
        print("\nShutdown requested", file=sys.stderr)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
