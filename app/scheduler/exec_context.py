"""
Shared execution context variables.

Thin module imported by both agentic_executor and capability_registry to avoid
circular imports. All vars are ContextVar so each asyncio task gets its own
isolated copy.
"""
from contextvars import ContextVar

# Set True by the security gate — unlocks ask_user for security escalations.
cv_gate_pending: ContextVar[bool] = ContextVar("exec_gate_pending", default=False)

# Set True by dispatch_subtask when role resolution fails — unlocks ask_user
# so the orchestrator can ask the user which role to use instead of silently failing.
cv_dispatch_blocked: ContextVar[bool] = ContextVar("exec_dispatch_blocked", default=False)
