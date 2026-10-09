"""Per-task attributes on a shared executor.

One AgenticExecutor / CodingAgentExecutor instance serves every task in the process, and the
scheduler runs tasks concurrently. State describing "the task being run right now" (role, policy
monitor, tool allowlist, pending permission...) kept as a plain `self.attr` is therefore shared:
one task silently overwrites another's across an `await`. That is what forced max_concurrent=1
(2026-07-22) and left the local models as the only lane in use.

`TaskLocal` backs an attribute with a ContextVar, so each asyncio task sees only its own value while
all existing `self._x` reads and writes keep working unchanged. An unset attribute reads as its
declared default (never another task's value).
"""
from contextvars import ContextVar
from typing import Any, Callable, Optional


class TaskLocal:
    def __init__(self, default: Any = None, factory: Optional[Callable[[], Any]] = None):
        self._default, self._factory = default, factory
        self._var: Optional[ContextVar] = None
        self._name = ""

    def __set_name__(self, owner, name):
        self._name = name
        self._var = ContextVar(f"{owner.__name__}.{name}")

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        try:
            return self._var.get()
        except LookupError:
            return self._factory() if self._factory else self._default

    def __set__(self, obj, value):
        self._var.set(value)
