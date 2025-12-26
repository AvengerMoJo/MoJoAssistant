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

try:
    from dotenv import load_dotenv
    env_path = project_root / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # dotenv is optional, continue without it
    pass

from app.mcp.server import UnifiedMCPServer


def setup_graceful_shutdown():
    """Setup graceful shutdown handlers to save memory before exit"""
    import signal
    import atexit
    from datetime import datetime
    
    def save_memory_on_shutdown():
        """Save current context and working memory before shutdown"""
        try:
            print("Graceful shutdown: saving current memory context...", file=sys.stderr)
            
            # Import here to avoid circular imports
            from app.services.memory_service import MemoryService
            from app.config.config_loader import load_embedding_config
            from app.memory.knowledge_manager import KnowledgeManager
            
            # Initialize minimal memory service for shutdown saving
            embedding_config = load_embedding_config()
            knowledge_manager = KnowledgeManager(embedding_config)
            memory_service = MemoryService(knowledge_manager)
            
            # Save current working memory if it has content
            if hasattr(memory_service, 'working_memory') and memory_service.working_memory:
                working_messages = memory_service.working_memory.get_messages()
                if working_messages:
                    print(f"Saving {len(working_messages)} working memory messages", file=sys.stderr)
                    # Store working memory as temporary context
                    temp_context = {
                        "type": "working_memory_backup",
                        "messages": working_messages,
                        "timestamp": datetime.now().isoformat(),
                        "backup_reason": "graceful_shutdown"
                    }
                    memory_service.active_memory.add_page(temp_context, "shutdown_backup")
            
            # Save current conversation if active
            if hasattr(memory_service, 'current_conversation') and memory_service.current_conversation:
                print(f"Saving current conversation with {len(memory_service.current_conversation)} messages", file=sys.stderr)
                memory_service.end_conversation()
            
            print("Memory context saved successfully", file=sys.stderr)
        except Exception as e:
            print(f"Error saving memory on shutdown: {e}", file=sys.stderr)
    
    # Register shutdown handlers
    signal.signal(signal.SIGTERM, lambda signum, frame: save_memory_on_shutdown())
    signal.signal(signal.SIGINT, lambda signum, frame: save_memory_on_shutdown())
    atexit.register(save_memory_on_shutdown)


def main():
    """Main entry point"""
    # Setup graceful shutdown first
    setup_graceful_shutdown()
    
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
        print(f"Main error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
