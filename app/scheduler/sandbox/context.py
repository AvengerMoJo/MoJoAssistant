"""Shared context variables for sandbox routing.

Placed in a dedicated module so both agentic_executor.py and
capability_registry.py can import without circular dependencies.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.scheduler.sandbox.base import SandboxHandle

_cv_sandbox_handle: ContextVar[Optional["SandboxHandle"]] = ContextVar(
    "_cv_sandbox_handle", default=None
)
