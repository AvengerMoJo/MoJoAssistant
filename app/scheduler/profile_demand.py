"""What the current task needs from a resource's measured profile, for the engine's shadow comparison.

An executor that knows its task uses tools sets the demand once; the pool reads it when it asks the engine the
shadow question. A ContextVar, because several tasks run concurrently and a plain attribute would let one task's
demand leak into another's (see the task-context isolation note). Shadow only for now: nothing here changes
which resource MoJoAssistant picks.
"""
from contextvars import ContextVar
from typing import Any, Dict, Optional

_demand: ContextVar = ContextVar("profile_demand", default=None)
_ALLOWED = {"min_level", "needs_tools", "needs_json", "min_concurrency"}


def set_demand(demand: Optional[Dict[str, Any]]) -> None:
    if demand is not None and not set(demand) <= _ALLOWED:
        raise ValueError(f"unknown profile demand keys {sorted(set(demand) - _ALLOWED)}")
    _demand.set(dict(demand) if demand else None)


def current() -> Optional[Dict[str, Any]]:
    d = _demand.get()
    return dict(d) if d else None
