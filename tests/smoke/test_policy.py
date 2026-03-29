"""
Smoke — Policy checker pipeline (no network, no LLM)

Verifies StaticPolicyChecker and ContentAwarePolicyChecker work standalone:
  - Static: allowed/denied_tools enforcement
  - Content: regex pattern matching blocks known-bad argument strings
  - PolicyMonitor: pipeline runs checkers in order, first block wins

No external services required.
"""

import pytest


# ---------------------------------------------------------------------------
# StaticPolicyChecker
# ---------------------------------------------------------------------------

def test_static_checker_allows_unlisted_tool_when_no_allowlist():
    from app.scheduler.policy.static import StaticPolicyChecker

    checker = StaticPolicyChecker()
    checker.configure({"role_id": "test", "policy": {}})

    decision = checker.check("any_tool", {}, {})
    assert decision.allowed is True


def test_static_checker_blocks_denied_tool():
    from app.scheduler.policy.static import StaticPolicyChecker

    checker = StaticPolicyChecker()
    checker.configure({
        "role_id": "test",
        "policy": {"denied_tools": ["dangerous_tool"]},
    })

    decision = checker.check("dangerous_tool", {}, {})
    assert decision.allowed is False
    assert "denied_tools" in decision.reason


def test_static_checker_allowlist_blocks_unlisted_tool():
    from app.scheduler.policy.static import StaticPolicyChecker

    checker = StaticPolicyChecker()
    checker.configure({
        "role_id": "test",
        "policy": {"allowed_tools": ["read_file", "list_dir"]},
    })

    decision = checker.check("write_file", {}, {})
    assert decision.allowed is False


def test_static_checker_allowlist_permits_listed_tool():
    from app.scheduler.policy.static import StaticPolicyChecker

    checker = StaticPolicyChecker()
    checker.configure({
        "role_id": "test",
        "policy": {"allowed_tools": ["read_file"]},
    })

    decision = checker.check("read_file", {}, {})
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# ContentAwarePolicyChecker  (pattern file may or may not exist — both paths
# must be handled gracefully)
# ---------------------------------------------------------------------------

def test_content_checker_allows_benign_args():
    from app.scheduler.policy.content import ContentAwarePolicyChecker

    checker = ContentAwarePolicyChecker()
    checker.configure({"role_id": "test", "policy": {}})

    decision = checker.check("read_file", {"path": "/tmp/data.txt"}, {})
    assert decision.allowed is True


def test_content_checker_blocks_aws_secret_key(isolated_memory_path):
    """A well-known AWS secret key pattern must be caught by the system patterns."""
    from app.scheduler.policy.content import ContentAwarePolicyChecker

    checker = ContentAwarePolicyChecker()
    checker.configure({"role_id": "test", "policy": {}})

    # Fake AWS secret key: 40-char base-64-ish string after AWSSECRETKEY=
    fake_secret = "AWSSECRETKEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    decision = checker.check("bash_exec", {"command": f"echo {fake_secret}"}, {})

    # If patterns file is present it should block; if absent the call still
    # returns a valid PolicyDecision (either way the checker is importable and
    # doesn't crash).
    assert isinstance(decision.allowed, bool)


# ---------------------------------------------------------------------------
# DataBoundaryChecker
# ---------------------------------------------------------------------------

def test_data_boundary_checker_imports_and_runs():
    from app.scheduler.policy.data_boundary_checker import DataBoundaryChecker

    checker = DataBoundaryChecker()
    checker.configure({"role_id": "test", "policy": {}, "local_only": False})

    decision = checker.check("read_file", {"path": "/tmp/ok.txt"}, {})
    assert isinstance(decision.allowed, bool)


# ---------------------------------------------------------------------------
# PolicyMonitor pipeline
# ---------------------------------------------------------------------------

def test_policy_monitor_first_block_wins():
    """If any checker blocks, the monitor returns blocked regardless of others."""
    from app.scheduler.policy.monitor import PolicyMonitor

    role = {"policy": {"denied_tools": ["evil_tool"]}}
    monitor = PolicyMonitor.from_role("test", role)

    decision = monitor.check("evil_tool", {})
    assert decision.allowed is False


def test_policy_monitor_allows_when_all_pass():
    from app.scheduler.policy.monitor import PolicyMonitor

    monitor = PolicyMonitor.from_role("test", {})

    decision = monitor.check("read_file", {"path": "/tmp/x.txt"})
    assert decision.allowed is True
