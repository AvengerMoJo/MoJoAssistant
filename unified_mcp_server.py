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


def create_app():
    """
    Factory function to create FastAPI app for uvicorn reload mode
    This is called by uvicorn when using factory=True
    """
    import asyncio
    from app.mcp.adapters.http import HTTPAdapter

    server = UnifiedMCPServer()

    # Initialize engine synchronously for factory mode
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(server.engine.initialize())
    server.logger = server.engine.logger

    # Create adapter
    legacy_config = {
        "api_key": server.app_config.server.api_key,
        "cors_origins": ",".join(server.app_config.server.cors_origins),
        "log_level": server.app_config.logging.level,
    }

    adapter = HTTPAdapter(server.engine, legacy_config)
    adapter.set_logger(server.logger)

    # Create and return FastAPI app
    app = adapter.create_app()

    if server.logger:
        server.logger.info("Development server initialized with hot reload")

    return app


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

  # HTTP mode with auto-reload (Development)
  python unified_mcp_server.py --mode http --port 8000 --reload
        """
    )
    
    parser.add_argument("--mode", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on code changes (development only)"
    )

    args = parser.parse_args()

    server = UnifiedMCPServer()

    try:
        if args.mode == "stdio":
            print("Starting MCP Server in STDIO mode", file=sys.stderr)
            asyncio.run(server.run_stdio())
        else:
            reload_mode = " (auto-reload enabled)" if args.reload else ""
            print(f"Starting MCP Server in HTTP mode on {args.host}:{args.port}{reload_mode}", file=sys.stderr)
            asyncio.run(server.run_http(args.host, args.port, reload=args.reload))
    except KeyboardInterrupt:
        print("\nShutdown requested", file=sys.stderr)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
