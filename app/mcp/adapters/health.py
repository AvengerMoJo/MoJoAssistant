"""Health check endpoint implementation."""

import time
import json
from datetime import datetime, timezone


async def api_health_check(engine):
    """Return system status JSON for /api/health endpoint."""
    try:
        uptime = time.time() - engine.start_time
        try:
            import psutil
            process = psutil.Process()
            memory_usage = {
                "rss_mb": round(process.memory_info().rss / 1024 / 1024, 2),
                "vms_mb": round(process.memory_info().vms / 1024 / 1024, 2),
            }
        except ImportError:
            memory_usage = {"rss_mb": 0, "vms_mb": 0}

        return {
            "status": "healthy",
            "version": "1.0.0",
            "uptime": round(uptime, 2),
            "memory_usage": memory_usage,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {
            "status": "error",
            "version": "1.0.0",
            "uptime": 0,
            "memory_usage": {"rss_mb": 0, "vms_mb": 0},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        }
