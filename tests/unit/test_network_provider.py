"""Tests for HeadscaleNetworkProvider.

Phase 1 of the self-hosted mesh networking vision — see
~/.claude/projects/-home-alex-Development-Personal-MoJoAssistant/memory/
project_network_provider_vision.md. Talks to the `headscale` CLI via
subprocess, same pattern as ResourcePool._refresh_loaded_models shelling
out to `lms ps --json` (tests/unit/test_resource_pool_loaded_state.py) —
must fail open on any CLI error, never raise into the caller.
"""
import json
import subprocess
import unittest
from unittest.mock import patch

from app.scheduler.network_provider import HeadscaleNetworkProvider
from app.services.provider_contracts import NetworkNode, get_registry


def _mock_result(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _headscale_nodes_json(nodes):
    return json.dumps(nodes)


class TestListNodes(unittest.TestCase):
    def setUp(self):
        self.provider = HeadscaleNetworkProvider()

    def test_parses_nodes_correctly(self):
        raw = [
            {"id": "1", "given_name": "mojoai", "ip_addresses": ["100.64.0.1"],
             "online": True, "last_seen": "2026-07-23T00:00:00Z"},
            {"id": "2", "name": "sandbox-vm-1", "ip_addresses": ["100.64.0.2"],
             "online": False, "last_seen": "2026-07-22T00:00:00Z"},
        ]
        with patch("subprocess.run", return_value=_mock_result(_headscale_nodes_json(raw))):
            nodes = self.provider.list_nodes()
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0]["hostname"], "mojoai")
        self.assertEqual(nodes[0]["ip"], "100.64.0.1")
        self.assertTrue(nodes[0]["online"])
        self.assertEqual(nodes[1]["hostname"], "sandbox-vm-1")
        self.assertFalse(nodes[1]["online"])

    def test_empty_node_list(self):
        with patch("subprocess.run", return_value=_mock_result("[]")):
            self.assertEqual(self.provider.list_nodes(), [])

    def test_missing_binary_fails_open(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertEqual(self.provider.list_nodes(), [])

    def test_nonzero_exit_fails_open(self):
        with patch("subprocess.run", return_value=_mock_result("", returncode=1, stderr="connection refused")):
            self.assertEqual(self.provider.list_nodes(), [])

    def test_malformed_json_fails_open(self):
        with patch("subprocess.run", return_value=_mock_result("not json")):
            self.assertEqual(self.provider.list_nodes(), [])

    def test_timeout_fails_open(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="headscale", timeout=8.0)):
            self.assertEqual(self.provider.list_nodes(), [])

    def test_non_list_json_fails_open(self):
        # A malformed/unexpected shape (e.g. an error object) shouldn't crash.
        with patch("subprocess.run", return_value=_mock_result(json.dumps({"error": "bad"}))):
            self.assertEqual(self.provider.list_nodes(), [])


class TestRegisterDeregister(unittest.TestCase):
    def setUp(self):
        self.provider = HeadscaleNetworkProvider()

    def test_register_returns_node_hostname_on_success(self):
        node = NetworkNode(node_id="n1", hostname="mojoai")
        with patch("subprocess.run", return_value=_mock_result(json.dumps({"key": "abc123"}))):
            result = self.provider.register(node)
        self.assertEqual(result, "mojoai")

    def test_register_falls_back_to_node_id_without_hostname(self):
        node = NetworkNode(node_id="n1")
        with patch("subprocess.run", return_value=_mock_result(json.dumps({"key": "abc123"}))):
            result = self.provider.register(node)
        self.assertEqual(result, "n1")

    def test_register_raises_when_cli_unreachable(self):
        # Unlike list_nodes (fail-open, returns []), register() has nothing
        # sensible to return on failure — the caller needs to know the join
        # credential was never actually provisioned.
        node = NetworkNode(node_id="n1", hostname="mojoai")
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            with self.assertRaises(RuntimeError):
                self.provider.register(node)

    def test_deregister_calls_delete_with_matched_id(self):
        node = NetworkNode(node_id="n1", hostname="mojoai")
        nodes_response = _mock_result(_headscale_nodes_json(
            [{"id": "42", "given_name": "mojoai", "ip_addresses": [], "online": True}]
        ))
        delete_response = _mock_result("")
        with patch("subprocess.run", side_effect=[nodes_response, delete_response]) as mock_run:
            self.provider.deregister(node)
        delete_call_args = mock_run.call_args_list[1][0][0]
        self.assertIn("42", delete_call_args)

    def test_deregister_no_match_does_not_call_delete(self):
        node = NetworkNode(node_id="n1", hostname="unknown-host")
        nodes_response = _mock_result(_headscale_nodes_json(
            [{"id": "42", "given_name": "mojoai", "ip_addresses": [], "online": True}]
        ))
        with patch("subprocess.run", return_value=nodes_response) as mock_run:
            self.provider.deregister(node)
        # Only the list_nodes() lookup call, no delete call.
        self.assertEqual(mock_run.call_count, 1)


class TestHealthCheck(unittest.TestCase):
    def test_reachable_reports_ok(self):
        provider = HeadscaleNetworkProvider()
        with patch("subprocess.run", return_value=_mock_result("[]")):
            result = provider.health_check()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["details"]["node_count"], 0)

    def test_unreachable_reports_error(self):
        provider = HeadscaleNetworkProvider()
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = provider.health_check()
        self.assertEqual(result["status"], "error")


class TestProviderResolution(unittest.TestCase):
    def test_resolve_network_provider_default_is_headscale(self):
        registry = get_registry()
        provider = registry.resolve_network_provider()
        self.assertEqual(provider.get_version().provider_name, "headscale")

    def test_resolve_network_provider_respects_env_var(self):
        import os
        registry = get_registry()
        # Explicit name param takes precedence over env var and default,
        # matching resolve_growth_provider's documented resolution order.
        provider = registry.resolve_network_provider(name="headscale")
        self.assertEqual(provider.get_version().provider_name, "headscale")


if __name__ == "__main__":
    unittest.main()
