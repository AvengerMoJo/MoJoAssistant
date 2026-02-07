#!/usr/bin/env python3
"""
FastAPI app factory for hot reload support
This module exports 'app' for uvicorn to reload

Usage for development with hot reload:
    uvicorn app_factory:app --reload --host 0.0.0.0 --port 8000

Or use the convenience script:
    ./run_dev.sh
"""
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        pass

# Load environment first
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from app.mcp.server import UnifiedMCPServer
from app.mcp.adapters.http import HTTPAdapter

# Create server
server = UnifiedMCPServer()

# Note: Engine initialization will happen in FastAPI startup event
# We can't do async init at module level, so the HTTPAdapter handles it

# Initialize engine first (must be done before creating app)
import asyncio

async def _init():
    await server.engine.initialize()
    server.logger = server.engine.logger

# Run initialization synchronously at module load
# This is safe because uvicorn imports the module in the main process
asyncio.run(_init())

# Create HTTP adapter
legacy_config = {
    "api_key": server.app_config.server.api_key,
    "cors_origins": ",".join(server.app_config.server.cors_origins),
    "log_level": server.app_config.logging.level,
}

adapter = HTTPAdapter(server.engine, legacy_config)
adapter.set_logger(server.logger)

# Create and export the FastAPI app
app = adapter.create_app()

# Log that hot reload is enabled
if server.logger:
    server.logger.info("App factory loaded - hot reload enabled")

if __name__ == "__main__":
    import uvicorn
    print("Starting development server with hot reload...")
    print("Edit any file in ./app/ and it will auto-reload!")
    uvicorn.run(
        "app_factory:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["./app"],
        log_level="info"
    )
