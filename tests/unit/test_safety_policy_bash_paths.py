"""Regression test: bash_exec's blocked-path check must not treat every
path as targeting root.

Found live 2026-09-23: SafetyPolicy.check_tool_execution() used
`if blocked in command` with blocked_paths[0] == "/" -- a bare substring
test against the single-character root path, true for virtually any real
shell command (every path contains "/"). This blocked project_sentinel's
routine `ls ~/.memory/projects/*.json` (a fully in-sandbox, allowed-path
read) with "Command targets blocked path '/'", which the agent then
reported to the user as an unresolvable "security restriction."
"""

from __future__ import annotations

import unittest

from app.scheduler.safety_policy import SafetyPolicy


def _high_danger_tool():
    return {"danger_level": "high"}


class TestBashBlockedPathCheck(unittest.TestCase):
    def setUp(self):
        # Use the default in-memory policy (no file I/O) by pointing at a
        # path that doesn't exist -- _load_policy() falls back to defaults.
        self.policy = SafetyPolicy(policy_path="/tmp/__nonexistent_safety_policy__.json")

    def test_memory_glob_read_is_allowed(self):
        result = self.policy.check_tool_execution(
            "bash_exec", _high_danger_tool(),
            {"command": "ls ~/.memory/projects/*.json"},
        )
        self.assertTrue(result["allowed"], result.get("reason"))

    def test_memory_subdir_read_is_allowed(self):
        result = self.policy.check_tool_execution(
            "bash_exec", _high_danger_tool(),
            {"command": "cat ~/.memory/scheduler_tasks.json"},
        )
        self.assertTrue(result["allowed"], result.get("reason"))

    def test_command_with_no_path_arguments_is_allowed(self):
        result = self.policy.check_tool_execution(
            "bash_exec", _high_danger_tool(), {"command": "echo hello world"},
        )
        self.assertTrue(result["allowed"], result.get("reason"))

    def test_rm_rf_root_is_still_blocked(self):
        result = self.policy.check_tool_execution(
            "bash_exec", _high_danger_tool(), {"command": "rm -rf /"},
        )
        self.assertFalse(result["allowed"])
        self.assertIn("/", result["reason"])

    def test_etc_passwd_is_still_blocked(self):
        result = self.policy.check_tool_execution(
            "bash_exec", _high_danger_tool(), {"command": "cat /etc/passwd"},
        )
        self.assertFalse(result["allowed"])

    def test_var_subpath_is_still_blocked(self):
        result = self.policy.check_tool_execution(
            "bash_exec", _high_danger_tool(), {"command": "rm -rf /var/log/syslog"},
        )
        self.assertFalse(result["allowed"])

    def test_low_danger_bash_still_rejected_before_path_check(self):
        result = self.policy.check_tool_execution(
            "bash_exec", {"danger_level": "low"},
            {"command": "ls ~/.memory/projects/*.json"},
        )
        self.assertFalse(result["allowed"])
        self.assertIn("danger", result["reason"].lower())

    def test_unparseable_command_falls_back_to_whitespace_split(self):
        """Unbalanced quotes must not crash the check."""
        result = self.policy.check_tool_execution(
            "bash_exec", _high_danger_tool(), {"command": 'echo "unterminated'},
        )
        # Should not raise; either allowed or blocked, but must return cleanly.
        self.assertIn("allowed", result)


if __name__ == "__main__":
    unittest.main()
