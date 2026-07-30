"""
Minimal shared API key vault — one place to store provider secrets instead
of scattering them across resource_pool.json's inline api_key/api_key_env
fields and OpenCode's own per-server `password` field in
opencode-mcp-tool-servers.json.

Deliberately small (Phase A of the unified provider/resource-pool work —
see project_unified_provider_resource_pool_vision memory): a flat
{name: secret} JSON map, one resolver function, additive everywhere it's
wired in. Existing api_key/api_key_env/password fields keep working
unchanged — key_ref/password_ref are opt-in, not a forced migration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.config.paths import get_memory_subpath

VAULT_PATH = Path(get_memory_subpath("config/api_keys.json"))


def resolve_api_key(name: Optional[str]) -> Optional[str]:
    """
    Look up a named secret in the vault (~/.memory/config/api_keys.json).

    Returns None if name is falsy, the vault file doesn't exist, or the
    name isn't found — callers should fall back to their own existing
    resolution chain, never treat a missing vault as an error.
    """
    if not name:
        return None
    if not VAULT_PATH.exists():
        return None
    try:
        data = json.loads(VAULT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    value = data.get(name)
    return value if isinstance(value, str) and value else None
