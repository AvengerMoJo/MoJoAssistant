"""
Unit tests for the pluggable PolicyMonitor checker pipeline.

Covers:
  - StaticPolicyChecker  (allowed_tools ceiling, denied_tools, per-call limits)
  - ContentAwarePolicyChecker  (regex pattern blocking)
  - DataBoundaryChecker  (allow_external_mcp, allowed_tiers)
  - ContextAwarePolicyChecker  (violation count ceiling)
  - PolicyMonitor  (pipeline, first-block-wins, violation_total tracking)
  - local_only shorthand  (expands into data_boundary defaults)
"""

import unittest

from app.scheduler.policy.base import PolicyDecision
from app.scheduler.policy.static import StaticPolicyChecker
from app.scheduler.policy.content import ContentAwarePolicyChecker
from app.scheduler.policy.data_boundary_checker import DataBoundaryChecker
from app.scheduler.policy.context import ContextAwarePolicyChecker
from app.scheduler.policy.monitor import PolicyMonitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(**kwargs):
    """Minimal context dict for standalone checker tests."""
    return {"role_id": "test", "task_id": "t1", "policy": {}, "data_boundary": {}, **kwargs}


def _configured(checker_cls, context):
    checker = checker_cls()
    checker.configure(context)
    return checker


# ---------------------------------------------------------------------------
# StaticPolicyChecker
# ---------------------------------------------------------------------------

class TestStaticPolicyChecker(unittest.TestCase):

    def _make(self, policy):
        ctx = _ctx(policy=policy)
        return _configured(StaticPolicyChecker, ctx)

    def test_allows_when_no_policy(self):
        checker = self._make({})
        d = checker.check("bash_exec", {}, _ctx())
        self.assertTrue(d.allowed)

    def test_allowed_tools_ceiling_blocks_unlisted(self):
        checker = self._make({"allowed_tools": ["memory_search"]})
        d = checker.check("bash_exec", {}, _ctx(policy={"allowed_tools": ["memory_search"]}))
        self.assertFalse(d.allowed)
        self.assertIn("bash_exec", d.reason)

    def test_allowed_tools_ceiling_permits_listed(self):
        checker = self._make({"allowed_tools": ["bash_exec", "memory_search"]})
        d = checker.check("bash_exec", {}, _ctx(policy={"allowed_tools": ["bash_exec"]}))
        self.assertTrue(d.allowed)

    def test_denied_tools_blocks(self):
        checker = self._make({"denied_tools": ["rm_rf"]})
        d = checker.check("rm_rf", {}, _ctx(policy={"denied_tools": ["rm_rf"]}))
        self.assertFalse(d.allowed)

    def test_per_call_limit_blocks_after_threshold(self):
        # StaticPolicyChecker uses "max_{tool}_per_task" key + record_call() counting.
        policy = {"max_bash_exec_per_task": 2}
        ctx = _ctx(policy=policy)
        checker = _configured(StaticPolicyChecker, ctx)
        checker.record_call("bash_exec")
        checker.record_call("bash_exec")
        d = checker.check("bash_exec", {}, ctx)
        self.assertFalse(d.allowed)
        self.assertIn("limit", d.reason.lower())

    def test_per_call_limit_allows_below_threshold(self):
        policy = {"max_bash_exec_per_task": 3}
        ctx = _ctx(policy=policy)
        checker = _configured(StaticPolicyChecker, ctx)
        checker.record_call("bash_exec")
        checker.record_call("bash_exec")
        d = checker.check("bash_exec", {}, ctx)
        self.assertTrue(d.allowed)


# ---------------------------------------------------------------------------
# ContentAwarePolicyChecker
# ---------------------------------------------------------------------------

class TestContentAwarePolicyChecker(unittest.TestCase):

    def _make(self, patterns, enabled=True):
        """Build a ContentAwarePolicyChecker with injected patterns."""
        checker = ContentAwarePolicyChecker()
        checker._enabled = enabled
        checker._compiled = patterns
        return checker

    def test_blocks_on_pattern_match(self):
        pattern = {"name": "secret_key", "regex": r"sk-[A-Za-z0-9]{20,}", "severity": "block",
                   "description": "API key detected"}
        checker = self._make([pattern])
        d = checker.check("bash_exec", {"command": "echo sk-abc123def456ghi789jkl0mn"}, _ctx())
        self.assertFalse(d.allowed)
        self.assertIn("secret_key", d.reason)

    def test_allows_when_no_match(self):
        pattern = {"name": "secret_key", "regex": r"sk-[A-Za-z0-9]{20,}", "severity": "block",
                   "description": "API key"}
        checker = self._make([pattern])
        d = checker.check("bash_exec", {"command": "ls -la"}, _ctx())
        self.assertTrue(d.allowed)

    def test_warn_severity_still_blocks(self):
        # Both warn and block severity halt the call — warn only affects logging severity.
        pattern = {"name": "phone", "regex": r"\d{3}-\d{4}", "severity": "warn",
                   "description": "Phone number"}
        checker = self._make([pattern])
        d = checker.check("send_message", {"body": "call 555-1234"}, _ctx())
        self.assertFalse(d.allowed)
        self.assertEqual(d.metadata.get("pattern_severity"), "warn")

    def test_disabled_allows_everything(self):
        pattern = {"name": "secret_key", "regex": r"sk-.*", "severity": "block", "description": "key"}
        checker = self._make([pattern], enabled=False)
        d = checker.check("bash_exec", {"command": "sk-secret"}, _ctx())
        self.assertTrue(d.allowed)

    def test_invalid_regex_skipped(self):
        bad = {"name": "bad", "regex": r"[invalid", "severity": "block", "description": "bad"}
        checker = self._make([bad])
        d = checker.check("bash_exec", {}, _ctx())
        self.assertTrue(d.allowed)  # invalid regex is skipped, not a crash


# ---------------------------------------------------------------------------
# DataBoundaryChecker
# ---------------------------------------------------------------------------

class TestDataBoundaryChecker(unittest.TestCase):

    def _make(self, allow_external_mcp=True):
        ctx = _ctx(data_boundary={"allow_external_mcp": allow_external_mcp})
        return _configured(DataBoundaryChecker, ctx)

    def test_blocks_external_mcp_when_disallowed(self):
        checker = self._make(allow_external_mcp=False)
        d = checker.check("tmux__list-sessions", {}, _ctx())
        self.assertFalse(d.allowed)
        self.assertIn("tmux__list-sessions", d.reason)

    def test_allows_external_mcp_when_permitted(self):
        checker = self._make(allow_external_mcp=True)
        d = checker.check("tmux__list-sessions", {}, _ctx())
        self.assertTrue(d.allowed)

    def test_allows_builtin_when_external_mcp_disallowed(self):
        checker = self._make(allow_external_mcp=False)
        d = checker.check("bash_exec", {}, _ctx())
        self.assertTrue(d.allowed)  # no __ in name → not an external MCP tool

    def test_double_underscore_detection(self):
        checker = self._make(allow_external_mcp=False)
        d = checker.check("playwright__browser_navigate", {}, _ctx())
        self.assertFalse(d.allowed)

    def test_default_allows_external_mcp(self):
        ctx = _ctx(data_boundary={})
        checker = _configured(DataBoundaryChecker, ctx)
        d = checker.check("some__external_tool", {}, ctx)
        self.assertTrue(d.allowed)


# ---------------------------------------------------------------------------
# ContextAwarePolicyChecker
# ---------------------------------------------------------------------------

class TestContextAwarePolicyChecker(unittest.TestCase):

    def _make(self, max_violations):
        ctx = _ctx(policy={"context_rules": {"max_violations_before_halt": max_violations}},
                   violation_total=0)
        return _configured(ContextAwarePolicyChecker, ctx)

    def test_blocks_when_ceiling_reached(self):
        checker = self._make(max_violations=3)
        ctx = _ctx(violation_total=3)
        d = checker.check("bash_exec", {}, ctx)
        self.assertFalse(d.allowed)
        self.assertIn("3", d.reason)

    def test_allows_below_ceiling(self):
        checker = self._make(max_violations=3)
        ctx = _ctx(violation_total=2)
        d = checker.check("bash_exec", {}, ctx)
        self.assertTrue(d.allowed)

    def test_allows_when_ceiling_is_zero(self):
        checker = self._make(max_violations=0)
        ctx = _ctx(violation_total=999)
        d = checker.check("bash_exec", {}, ctx)
        self.assertTrue(d.allowed)  # 0 means disabled

    def test_blocks_when_ceiling_exceeded(self):
        checker = self._make(max_violations=2)
        ctx = _ctx(violation_total=5)
        d = checker.check("bash_exec", {}, ctx)
        self.assertFalse(d.allowed)


# ---------------------------------------------------------------------------
# PolicyMonitor (pipeline)
# ---------------------------------------------------------------------------

class TestPolicyMonitor(unittest.TestCase):

    def _monitor_from_role(self, role):
        return PolicyMonitor.from_role("test_role", role, task_id="t1")

    def test_empty_monitor_allows_everything(self):
        monitor = PolicyMonitor(role_id=None, policy=None)
        d = monitor.check("any_tool", {})
        self.assertTrue(d.allowed)

    def test_first_block_wins(self):
        """StaticPolicyChecker blocks before ContentAwarePolicyChecker runs."""
        role = {"policy": {"checkers": ["static", "content"],
                           "allowed_tools": ["memory_search"]}}
        monitor = self._monitor_from_role(role)
        d = monitor.check("bash_exec", {})
        self.assertFalse(d.allowed)
        self.assertEqual(d.checker, "static")

    def test_violation_total_increments_on_block(self):
        role = {"policy": {"checkers": ["static"], "allowed_tools": ["memory_search"]}}
        monitor = self._monitor_from_role(role)
        monitor.check("bash_exec", {})
        monitor.check("bash_exec", {})
        self.assertEqual(monitor._violation_total, 2)

    def test_context_checker_halts_after_ceiling(self):
        # Context checker is last — it fires when a previously-allowed tool call
        # arrives but violation_total has already hit the ceiling.
        # Pipeline: static (blocks ext__tool via denied_tools) → context (halts on count).
        # After 2 denials by static, context halts on the 3rd call even for a
        # tool that would normally be allowed (bash_exec).
        role = {
            "policy": {
                "checkers": ["static", "context"],
                "denied_tools": ["ext__tool"],
                "context_rules": {"max_violations_before_halt": 2},
            },
        }
        monitor = self._monitor_from_role(role)
        monitor.check("ext__tool", {})   # blocked by static → violation 1
        monitor.check("ext__tool", {})   # blocked by static → violation 2 (at ceiling)
        d = monitor.check("bash_exec", {})  # context sees violation_total=2 → halts
        self.assertFalse(d.allowed)
        self.assertEqual(d.checker, "context")

    def test_record_call_increments_counts(self):
        monitor = PolicyMonitor(role_id=None, policy=None)
        monitor.record_call("bash_exec")
        monitor.record_call("bash_exec")
        monitor.record_call("memory_search")
        self.assertEqual(monitor._context["call_counts"]["bash_exec"], 2)
        self.assertEqual(monitor._context["call_counts"]["memory_search"], 1)

    def test_unknown_checker_name_skipped(self):
        role = {"policy": {"checkers": ["static", "nonexistent_checker"]}}
        monitor = self._monitor_from_role(role)
        # Should not raise; nonexistent_checker is simply skipped
        d = monitor.check("bash_exec", {})
        self.assertIsInstance(d, PolicyDecision)


# ---------------------------------------------------------------------------
# local_only shorthand
# ---------------------------------------------------------------------------

class TestLocalOnlyShorthand(unittest.TestCase):

    def test_local_only_sets_allow_external_mcp_false(self):
        role = {"local_only": True, "policy": {"checkers": ["data_boundary"]}}
        monitor = PolicyMonitor.from_role("r", role)
        self.assertFalse(monitor.data_boundary.get("allow_external_mcp"))

    def test_local_only_sets_allowed_tiers_free(self):
        role = {"local_only": True, "policy": {"checkers": ["data_boundary"]}}
        monitor = PolicyMonitor.from_role("r", role)
        self.assertEqual(monitor.data_boundary.get("allowed_tiers"), ["free"])

    def test_local_only_does_not_override_explicit_data_boundary(self):
        role = {
            "local_only": True,
            "data_boundary": {"allow_external_mcp": True, "allowed_tiers": ["free", "free_api"]},
            "policy": {"checkers": ["data_boundary"]},
        }
        monitor = PolicyMonitor.from_role("r", role)
        # Explicit values take precedence over local_only defaults
        self.assertTrue(monitor.data_boundary.get("allow_external_mcp"))
        self.assertEqual(monitor.data_boundary.get("allowed_tiers"), ["free", "free_api"])

    def test_local_only_blocks_external_mcp_tool(self):
        role = {"local_only": True, "policy": {"checkers": ["data_boundary"]}}
        monitor = PolicyMonitor.from_role("r", role)
        d = monitor.check("some__external_tool", {})
        self.assertFalse(d.allowed)

    def test_local_only_allows_builtin_tool(self):
        role = {"local_only": True, "policy": {"checkers": ["data_boundary"]}}
        monitor = PolicyMonitor.from_role("r", role)
        d = monitor.check("bash_exec", {})
        self.assertTrue(d.allowed)

    def test_without_local_only_no_defaults_applied(self):
        role = {"policy": {"checkers": ["data_boundary"]}}
        monitor = PolicyMonitor.from_role("r", role)
        d = monitor.check("some__external_tool", {})
        self.assertTrue(d.allowed)  # no restriction without local_only


if __name__ == "__main__":
    unittest.main()
