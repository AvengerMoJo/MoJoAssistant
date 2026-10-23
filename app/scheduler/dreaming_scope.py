"""How far a dreaming run's text may travel, decided by where the text came from.

Dreaming reads two kinds of text:
  conversation  -- the owner's own chats and memory (nightly dreaming, chat bridge, anything untagged)
  task_output   -- what a role did on a scheduled task (session transcript, final report)

Each kind has its own widest allowed place (resource_pool DATA_SCOPES), from config
`dreaming.scopes`; a kind not listed falls back to `dreaming.max_data_scope`, whose default is the safe
own_network. A role that declares its own `data_scope` (Anna: own_network) caps its task output too.
Unknown kinds are an error: a typo must not widen where the owner's text goes.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

SOURCES = ("conversation", "task_output")
DATA_SCOPES = ("local_host", "own_network", "third_party")  # narrowest -> widest, same order as resource_pool


def resolve_scope(dreaming_cfg: Optional[Dict[str, Any]], source: str, role_data_scope: Optional[str] = None) -> str:
    if source not in SOURCES:
        raise ValueError(f"dreaming source {source!r} must be one of {list(SOURCES)}")
    cfg = dreaming_cfg or {}
    scope = (cfg.get("scopes") or {}).get(source) or cfg.get("max_data_scope") or "own_network"
    for name, value in (("dreaming scope", scope), ("role data_scope", role_data_scope)):
        if value is not None and value not in DATA_SCOPES:
            raise ValueError(f"{name} {value!r} must be one of {list(DATA_SCOPES)}")
    if role_data_scope is not None and DATA_SCOPES.index(role_data_scope) < DATA_SCOPES.index(scope):
        scope = role_data_scope
    return scope
