"""
AuditLog — append-only record of every external boundary crossing.

Every call to a non-local resource (tier != 'free') is logged here with
metadata only — content is never stored. The log is never purged.

Record schema:
  {
    "ts":            "<ISO-8601 timestamp>",
    "task_id":       "<task id>",
    "role_id":       "<role id or null>",
    "resource_id":   "<resource id>",
    "resource_type": "local" | "api",
    "tier":          "free" | "free_api" | "paid",
    "model":         "<model name>",
    "tokens_in":     <int>,
    "tokens_out":    <int>,
    "tokens_total":  <int>
  }
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config.paths import get_memory_subpath


def _default_path() -> Path:
    return Path(get_memory_subpath("audit_log.jsonl"))
_lock = threading.Lock()


def append(
    *,
    task_id: str,
    role_id: Optional[str],
    resource_id: str,
    resource_type: str,
    tier: str,
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    tokens_total: int = 0,
    path: Optional[Path] = None,
) -> None:
    """Append one audit record to the log. Thread-safe, never raises."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "task_id": task_id,
        "role_id": role_id,
        "resource_id": resource_id,
        "resource_type": resource_type,
        "tier": tier,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_total": tokens_total,
    }
    log_path = path or _default_path()
    try:
        with _lock:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
    except Exception:
        pass  # audit logging must never break the calling code


def get(task_id: Optional[str] = None, limit: int = 100, path: Optional[Path] = None) -> list:
    """
    Read audit records, optionally filtered by task_id.
    Returns newest-first, capped at limit.
    """
    log_path = path or _default_path()
    if not log_path.exists():
        return []
    records = []
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if task_id is None or r.get("task_id") == task_id:
                        records.append(r)
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
    return list(reversed(records))[-limit:]
