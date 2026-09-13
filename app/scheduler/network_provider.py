"""Default NetworkProvider implementation (Headscale-backed).

Phase 1 of the self-hosted mesh networking vision (see
~/.claude/projects/-home-alex-Development-Personal-MoJoAssistant/memory/
project_network_provider_vision.md). Talks to a local Headscale server via
its CLI (subprocess), the same pattern as ResourcePool._refresh_loaded_models
shelling out to `lms ps --json` — the CLI already handles local auth via the
unix socket, avoiding extra HTTP-API token plumbing Phase 1 doesn't need yet.

Fails open on any error (missing binary, non-zero exit, malformed JSON):
a broken network-provider check must never crash anything that calls it,
same principle as the resource-pool loaded-state check.
"""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any, Dict, List, Optional

from app.services.provider_contracts import (
    NetworkNode,
    NetworkProvider,
    ProviderVersion,
)

logger = logging.getLogger(__name__)

DEFAULT_CLI_PATH = "headscale"
DEFAULT_USER = "mojo"
CLI_TIMEOUT_SECONDS = 8.0


class HeadscaleNetworkProvider(NetworkProvider):
    PROVIDER_NAME = "headscale"
    PROVIDER_VERSION = "1.0.0"
    CONTRACT_VERSION = "1.0"

    def __init__(
        self,
        cli_path: str = DEFAULT_CLI_PATH,
        user: str = DEFAULT_USER,
    ) -> None:
        self._cli_path = cli_path
        self._user = user

    def get_version(self) -> ProviderVersion:
        return ProviderVersion(
            provider_name=self.PROVIDER_NAME,
            provider_version=self.PROVIDER_VERSION,
            contract_version=self.CONTRACT_VERSION,
        )

    def _run_cli(self, args: List[str]) -> Optional[Any]:
        """Run a headscale CLI subcommand with --output json, parsed.

        Returns None on any failure (missing binary, non-zero exit, bad
        JSON) rather than raising — callers treat None as "couldn't reach
        Headscale right now," not a crash.
        """
        try:
            proc = subprocess.run(
                [self._cli_path, *args],
                capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            logger.warning("HeadscaleNetworkProvider: '%s' binary not found", self._cli_path)
            return None
        except subprocess.TimeoutExpired:
            logger.warning("HeadscaleNetworkProvider: CLI call timed out: %s", args)
            return None
        except Exception as e:
            logger.warning("HeadscaleNetworkProvider: CLI call failed: %s", e)
            return None

        if proc.returncode != 0:
            logger.warning(
                "HeadscaleNetworkProvider: '%s' exited %d: %s",
                " ".join(args), proc.returncode, proc.stderr[:200],
            )
            return None

        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            logger.warning("HeadscaleNetworkProvider: malformed JSON from CLI: %s", e)
            return None

    def register(self, node: NetworkNode) -> str:
        """Provision a join credential and return the node's expected
        stable hostname (Headscale assigns `<node-name>.<user>.<magic-dns-
        domain>` deterministically from the client's own hostname at join
        time — this does not itself join the node; joining happens
        client-side via `tailscale up --authkey=...`).
        """
        data = self._run_cli([
            "preauthkeys", "create", "--user", self._user,
            "--reusable", "--expiration", "24h", "--output", "json",
        ])
        if data is None:
            raise RuntimeError(
                f"Failed to provision a join credential for node '{node.node_id}' — "
                "Headscale CLI unreachable or errored"
            )
        # Hostname isn't known until the node actually joins and Headscale
        # assigns it — return the node's own declared hostname as the
        # expected value; callers should cross-check via list_nodes() after
        # the client-side join completes.
        return node.hostname or node.node_id

    def deregister(self, node: NetworkNode) -> None:
        nodes = self.list_nodes()
        match = next((n for n in nodes if n.get("hostname") == node.hostname
                      or n.get("id") == node.node_id), None)
        if match is None:
            logger.warning(
                "HeadscaleNetworkProvider: node '%s' not found, nothing to deregister",
                node.node_id,
            )
            return
        self._run_cli([
            "nodes", "delete", "--identifier", str(match.get("id")), "--force",
        ])

    @staticmethod
    def _parse_nodes(data: Any) -> List[Dict[str, Any]]:
        if not isinstance(data, list):
            return []
        return [
            {
                "id": n.get("id"),
                "hostname": n.get("given_name") or n.get("name"),
                "ip": (n.get("ip_addresses") or [None])[0],
                "online": bool(n.get("online")),
                "last_seen": n.get("last_seen"),
            }
            for n in data
            if isinstance(n, dict)
        ]

    def list_nodes(self) -> List[Dict[str, Any]]:
        data = self._run_cli(["nodes", "list", "--output", "json"])
        return self._parse_nodes(data) if data is not None else []

    def health_check(self) -> Dict[str, Any]:
        data = self._run_cli(["nodes", "list", "--output", "json"])
        reachable = data is not None
        nodes = self._parse_nodes(data) if reachable else []
        return {
            "status": "ok" if reachable else "error",
            "details": {"provider": self.PROVIDER_NAME, "node_count": len(nodes)},
        }
