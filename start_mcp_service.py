#!/usr/bin/env python3
"""
MCP Service Startup Script
Starts the MoJoAssistant Memory Communication Protocol service
"""
import os
import sys
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    parser = argparse.ArgumentParser(description="Start MoJoAssistant MCP Service")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0 for all interfaces)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--api-key", help="API key for authentication (optional)")
    parser.add_argument("--cors-origins", default="*", help="CORS allowed origins")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    
    args = parser.parse_args()
    
    # Set environment variables
    os.environ["MCP_HOST"] = args.host
    os.environ["MCP_PORT"] = str(args.port)
    os.environ["MCP_CORS_ORIGINS"] = args.cors_origins
    
    if args.api_key:
        os.environ["MCP_API_KEY"] = args.api_key
    
    print("🚀 Starting MoJoAssistant MCP Service")
    print("=" * 50)
    print(f"Host: {args.host} {'(all interfaces)' if args.host == '0.0.0.0' else '(localhost only)' if args.host == 'localhost' else ''}")
    print(f"Port: {args.port}")
    print(f"CORS Origins: {args.cors_origins}")
    print(f"API Key: {'Set' if args.api_key else 'Not set (public access)'}")
    print(f"Log Level: {args.log_level}")
    print(f"Auto-reload: {args.reload}")
    
    if args.host == "0.0.0.0":
        print("⚠️  Service will be accessible from external networks!")
        print("   Consider using --api-key for security in production")
    
    print("=" * 50)
    
    try:
        import uvicorn
        from app.mcp.mcp_service import app
        
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=args.log_level.lower(),
            access_log=True
        )
        
    except ImportError:
        print("❌ Error: FastAPI and uvicorn are required to run the MCP service")
        print("Install with: pip install fastapi uvicorn")
        return 1
    except KeyboardInterrupt:
        print("\n👋 MCP Service stopped by user")
        return 0
    except Exception as e:
        print(f"❌ Error starting MCP service: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
