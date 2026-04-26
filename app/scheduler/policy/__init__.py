"""
app.scheduler.policy — pluggable policy enforcement pipeline.

Public API (backwards-compatible with old policy_monitor.py):
    from app.scheduler.policy import PolicyMonitor, PolicyDecision, PolicyChecker

Extending:
    from app.scheduler.policy import PolicyChecker, PolicyDecision, PolicyMonitor

    class MyChecker(PolicyChecker):
        name = "my_checker"
        def check(self, tool_name, args, context):
            ...

    PolicyMonitor.register_checker("my_checker", MyChecker)
"""
# [hitl-orchestrator: generic]

from app.scheduler.policy.base import PolicyChecker, PolicyDecision
from app.scheduler.policy.static import StaticPolicyChecker
from app.scheduler.policy.content import ContentAwarePolicyChecker
from app.scheduler.policy.data_boundary_checker import DataBoundaryChecker
from app.scheduler.policy.context import ContextAwarePolicyChecker
from app.scheduler.policy.sensitive_domain import SensitiveDomainChecker
from app.scheduler.policy.relationship_coupler import get_trust_level, apply_trust_defaults
from app.scheduler.policy.monitor import PolicyMonitor

# Auto-register all built-in checkers
PolicyMonitor.register_checker("static", StaticPolicyChecker)
PolicyMonitor.register_checker("content", ContentAwarePolicyChecker)
PolicyMonitor.register_checker("data_boundary", DataBoundaryChecker)
PolicyMonitor.register_checker("context", ContextAwarePolicyChecker)
PolicyMonitor.register_checker("sensitive_domain", SensitiveDomainChecker)

__all__ = [
    "PolicyChecker",
    "PolicyDecision",
    "StaticPolicyChecker",
    "ContentAwarePolicyChecker",
    "DataBoundaryChecker",
    "ContextAwarePolicyChecker",
    "SensitiveDomainChecker",
    "get_trust_level",
    "apply_trust_defaults",
    "PolicyMonitor",
]
