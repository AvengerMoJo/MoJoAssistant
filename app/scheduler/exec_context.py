"""
Shared execution context variables.

Thin module imported by both agentic_executor and capability_registry to avoid
circular imports. All vars are ContextVar so each asyncio task gets its own
isolated copy.
"""
from contextvars import ContextVar
from typing import Optional

# Set True by the security gate — unlocks ask_user for security escalations.
cv_gate_pending: ContextVar[bool] = ContextVar("exec_gate_pending", default=False)

# Set True by dispatch_subtask when role resolution fails — unlocks ask_user
# so the orchestrator can ask the user which role to use instead of silently failing.
cv_dispatch_blocked: ContextVar[bool] = ContextVar("exec_dispatch_blocked", default=False)

# Per-task execution identity, set once at the start of AgenticExecutor.execute()
# and read by both agentic_executor and capability_registry (dispatch_subtask
# parent linkage, dispatch-depth cap, role-scoped memory_search, and the tool
# allowlist check). Moved here from plain instance attributes on the shared
# CapabilityRegistry/AgenticExecutor singletons 2026-08 -- see
# ~/.memory/research/scheduler_concurrency_context_race_2607.md. A plain
# instance attribute on a singleton reused across concurrently-running asyncio
# tasks is not isolated: task A's context can be silently overwritten by task
# B between an `await` yield and A's next read. ContextVar is per-asyncio-task
# by construction, so this class of race is structurally impossible once every
# read/write of "what task/role/context is currently executing" goes through
# these vars instead of `self.<attr>`.
cv_task_id: ContextVar[Optional[str]] = ContextVar("exec_task_id", default=None)
cv_dispatch_depth: ContextVar[int] = ContextVar("exec_dispatch_depth", default=0)
cv_role_id: ContextVar[Optional[str]] = ContextVar("exec_role_id", default=None)
cv_enabled_tools: ContextVar[Optional[list]] = ContextVar("exec_enabled_tools", default=None)
