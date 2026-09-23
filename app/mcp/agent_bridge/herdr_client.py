"""herdr client — shells out to the herdr CLI over SSH for the unified session view.

`agent_sessions_unified` (server.py) needs the human-surface session list that
herdr owns. herdr is driven from the bridge host via
`herdr --remote <user@host> agent list --json` — SSH socket forwarding with
key auth, no extra credentials (see docs/architecture/SSH_REMOTE_SANDBOX.md).

Error contract (per herdr's CLI, verified against its skill doc):
  - server errors: JSON on stderr, exit status 1
  - CLI syntax errors: exit status 2
This module never raises: it returns structured ok/error dicts so MCP tools
can degrade per host instead of failing the whole fleet view.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

HERDR_TIMEOUT = 30.0


def resolve_ssh_target(host_cfg: Dict[str, Any]) -> Optional[str]:
    """Derive the `user@host` herdr remote target from a registry host entry.

    Accepts either a string (`"ssh": "user@host"`) or an object
    (`"ssh": {"user": "...", "host": "..."}`). Absent/malformed → None,
    meaning herdr integration is unavailable for that host — never an error,
    matching the registry's optional-key convention.
    """
    ssh = host_cfg.get("ssh")
    if isinstance(ssh, str):
        target = ssh.strip()
        return target or None
    if isinstance(ssh, dict):
        user = (ssh.get("user") or "").strip()
        host = (ssh.get("host") or "").strip()
        if user and host:
            return f"{user}@{host}"
    return None


def _extract_agents(text: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Tolerantly pull the agent list out of `herdr agent list --json` output.

    The exact envelope has shifted between herdr versions (bare list,
    {"agents": [...]}, {"result": {"agents": [...]}}); accept all three
    rather than pinning the bridge to one release.
    """
    if not text.strip():
        return None, "empty output"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"non-JSON output: {str(exc)[:120]}"

    def _dicts(items: Any) -> List[Dict[str, Any]]:
        return [i for i in items if isinstance(i, dict)]

    if isinstance(data, list):
        return _dicts(data), None
    if isinstance(data, dict):
        for key in ("agents", "data", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return _dicts(value), None
            if isinstance(value, dict):
                for inner in ("agents", "data"):
                    if isinstance(value.get(inner), list):
                        return _dicts(value[inner]), None
    return None, "no agent list found in output"


async def list_remote_agents(
    ssh_target: str,
    timeout: float = HERDR_TIMEOUT,
) -> Dict[str, Any]:
    """Run `herdr --remote <ssh_target> agent list --json` and return the agents.

    Returns {"ok": True, "agents": [...]} on success; on failure
    {"ok": False, "kind": <classification>, "error": <human-readable>} where
    kind ∈ herdr_missing | timeout | cli_syntax | server_error | parse_error.
    """
    if not ssh_target or not ssh_target.strip():
        return {"ok": False, "kind": "cli_syntax", "error": "empty ssh_target"}

    try:
        proc = await asyncio.create_subprocess_exec(
            "herdr",
            "--remote",
            ssh_target,
            "agent",
            "list",
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "kind": "herdr_missing",
            "error": "herdr binary not found in PATH on the bridge host",
        }

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return {
            "ok": False,
            "kind": "timeout",
            "error": f"herdr --remote {ssh_target} timed out after {timeout:.0f}s",
        }

    stdout_text = stdout.decode("utf-8", errors="ignore").strip()
    stderr_text = stderr.decode("utf-8", errors="ignore").strip()

    if proc.returncode == 0:
        agents, parse_error = _extract_agents(stdout_text)
        if parse_error:
            return {
                "ok": False,
                "kind": "parse_error",
                "error": parse_error,
                "raw": (stdout_text or stderr_text)[:300],
            }
        return {"ok": True, "agents": agents, "ssh_target": ssh_target}

    detail = stderr_text or stdout_text or f"exit {proc.returncode}"

    if proc.returncode == 2:
        return {
            "ok": False,
            "kind": "cli_syntax",
            "error": f"herdr CLI rejected the invocation: {detail[:300]}",
        }

    parsed: Any = None
    if stderr_text:
        try:
            parsed = json.loads(stderr_text)
        except json.JSONDecodeError:
            parsed = None
    return {
        "ok": False,
        "kind": "server_error",
        "error": detail[:300],
        "stderr_json": parsed,
        "exit_code": proc.returncode,
    }
