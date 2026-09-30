#!/usr/bin/env python3
"""Standalone opencode v2 diagnostic.

Generic, bash-driven, works anywhere `opencode` is on PATH — this dev machine,
or dispatched via bash_exec/SSH to a fleet host. No AgentBridge coupling, no
MCP tool registration; any role with exec/terminal already runs this the same
way a human would.

Walks each stage and reports (never fixes automatically — every fix here
touches auth/credentials or a background service, so it's shown, not applied):

  1. opencode on PATH, version, debug paths sane (data dir + db file exist)
  2. opencode auth list -- every provider has a credential or an env-based
     fallback; flags one with neither
  3. opencode mcp list -- flags any failed/disabled server
  4. opencode plugin list + a log-tail scan for the known herdr/opencode v2
     plugin-format error ("Plugin must export a default definition...")
  5. opencode service status -- background service reachable

Secrets are never printed -- only provider/label names and (for LM Studio-style
sk-lm-XXXXXXXX:... tokens) the 8-char id prefix, to compare "which token" is in
play without ever showing the token itself.

Confirmed against opencode's own docs (opencode.ai/v2/docs), not just live
behavior: "Saved API keys and OAuth tokens live in the server's SQLite
database... A saved account takes precedence over an environment connection
for the same integration" (cli/providers) -- "V2 imports supported credentials
from the legacy auth.json... during its database migration. New and updated
credentials are stored in SQLite rather than written back to that file"
(same page) -- and troubleshooting explicitly says "Do not delete or edit
service files or the database while troubleshooting... make a backup before
inspecting persistent data with external tools." This script only reads;
never hand-edit opencode.db.

Usage:
  python3 scripts/doctor_opencode.py            # diagnose only
  python3 scripts/doctor_opencode.py --json      # machine-readable

Exit codes:
  0  all stages passed
  1  one or more stages failed or warned
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_TOKEN_ID_RE = re.compile(r"sk-lm-([A-Za-z0-9]{8}):[A-Za-z0-9]+")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _mask_secrets(s: str) -> str:
    """Replace any sk-lm-XXXXXXXX:<secret> with sk-lm-XXXXXXXX:<hidden> --
    keep the 8-char id (useful for spotting a stale-vs-new token mismatch)
    without ever surfacing the secret itself."""
    return _TOKEN_ID_RE.sub(r"sk-lm-\1:<hidden>", s)


def _run(args: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, _mask_secrets(_strip_ansi(r.stdout + r.stderr))
    except FileNotFoundError:
        return 127, f"{args[0]}: command not found"
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(args)} timed out ({timeout}s)"


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------


@dataclass
class StageResult:
    name: str
    status: str  # "ok" | "warn" | "fail" | "skipped"
    detail: str
    fix_command: Optional[str] = None  # shown, never run automatically


def stage_1_paths() -> StageResult:
    """opencode on PATH; its documented `opencode debug paths db` points at a
    real credential database. Uses the exact documented one-path-at-a-time
    form (`opencode debug paths <name>`, per opencode.ai/v2/docs/cli/providers)
    instead of parsing the full table -- one less thing to get wrong."""
    rc, out = _run(["opencode", "--version"])
    if rc != 0:
        return StageResult(
            "paths", "fail", f"opencode not runnable: {out[:150]}",
            fix_command="curl -fsSL https://opencode.ai/v2/install | bash  # read the script first",
        )
    version = out.strip().splitlines()[-1] if out.strip() else "unknown"

    rc, out = _run(["opencode", "debug", "paths", "db"])
    if rc != 0:
        return StageResult("paths", "warn", f"'opencode debug paths db' failed: {out[:150]}")
    db = Path(out.strip())
    if not db.exists():
        return StageResult(
            "paths", "warn",
            f"{version}, db path {db} doesn't exist yet "
            "(fine on a machine that has never run a session)",
        )
    return StageResult("paths", "ok", f"{version}, db at {db}")


def stage_2_auth() -> StageResult:
    """Cross-reference every provider *defined in config* against whether it
    actually has a way to authenticate: a resolved apiKey/headers value (shown
    as "***" by `opencode debug config` when present, absent when not), or a
    saved credential (`opencode auth list`).

    `opencode auth list` silently omits a provider that has neither -- it does
    NOT show it as "missing" -- so counting rows there (as an earlier version
    of this check did) misses exactly the dangerous case: a provider defined
    in opencode.json with no working auth at all. Confirmed live 2026-09-29 by
    deliberately stripping MoJoLLM's credential+header and observing it vanish
    from `auth list` (10 rows -> 9) instead of appearing as broken.
    """
    rc, out = _run(["opencode", "debug", "config"])
    if rc != 0:
        return StageResult("auth", "warn", f"'opencode debug config' failed: {out[:200]}")
    try:
        entries = json.loads(out)
        providers: dict = {}
        for e in entries:
            providers.update((e.get("info") or {}).get("providers") or {})
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        return StageResult("auth", "warn", f"could not parse 'opencode debug config': {e}")
    if not providers:
        return StageResult("auth", "warn", "no providers defined in config")

    rc2, auth_out = _run(["opencode", "auth", "list"])
    saved_names = {l.split("  ")[0].strip() for l in auth_out.splitlines() if l.strip()} if rc2 == 0 else set()

    unauthed = []
    for pid, p in providers.items():
        settings = p.get("settings") or {}
        # `headers` is a sibling of `settings`, not nested inside it (confirmed
        # live 2026-09-29 against `opencode debug config` output) -- checking
        # only `settings` missed a provider authenticated purely via headers.
        has_config_key = "apiKey" in settings or "headers" in p
        has_saved_cred = p.get("name") in saved_names
        if not has_config_key and not has_saved_cred:
            unauthed.append(pid)

    if unauthed:
        return StageResult(
            "auth", "fail",
            f"{len(unauthed)} provider(s) defined but have NO credential and NO "
            f"config apiKey/headers: {', '.join(unauthed)} -- invisible in "
            f"'opencode auth list' (it just omits them)",
            fix_command="opencode auth login <provider>  # needs a real interactive terminal",
        )
    return StageResult("auth", "ok", f"{len(providers)} provider(s), all have a credential or config key")


def stage_3_mcp() -> StageResult:
    """opencode mcp list -- flag any 'failed' server (disabled is fine)."""
    rc, out = _run(["opencode", "mcp", "list"])
    if rc != 0:
        return StageResult("mcp", "warn", f"'opencode mcp list' failed: {out[:200]}")
    failed = [l.strip() for l in out.splitlines() if l.strip().startswith("✗")]
    if failed:
        return StageResult(
            "mcp", "fail", f"{len(failed)} failed MCP server(s): {'; '.join(failed)[:200]}",
            fix_command="opencode mcp list  # then check that server's own logs/network reachability",
        )
    ok = [l for l in out.splitlines() if l.strip().startswith("✓")]
    return StageResult("mcp", "ok", f"{len(ok)} connected, 0 failed")


_PLUGIN_FORMAT_ERROR = "Plugin must export a default definition"


def stage_4_plugins() -> StageResult:
    """opencode plugin list + a log-tail scan for the known v1/v2 plugin
    export-format error (typically herdr's opencode integration predating v2:
    the required default export is `{id, setup(ctx)}` or `{id, effect}` per
    opencode.ai/v2/docs/build/plugins -- a v1-only `server()`-shaped plugin
    fails validation)."""
    rc, out = _run(["opencode", "plugin", "list"])
    plugin_summary = out.strip().splitlines()[-1] if rc == 0 and out.strip() else "(none registered)"

    rc2, out2 = _run(["opencode", "debug", "paths", "log"])
    log_hit = ""
    if rc2 == 0:
        log_dir = out2.strip()
        if log_dir:
            log_file = Path(log_dir) / "opencode.log"
            if log_file.exists():
                try:
                    # Binary-safe tail: read the file's last ~200KB only.
                    with open(log_file, "rb") as f:
                        f.seek(0, 2)
                        size = f.tell()
                        f.seek(max(0, size - 200_000))
                        tail = f.read().decode("utf-8", errors="ignore")
                    if _PLUGIN_FORMAT_ERROR in tail:
                        log_hit = _PLUGIN_FORMAT_ERROR
                except OSError:
                    pass

    if log_hit:
        herdr_rc, herdr_out = _run(["herdr", "integration", "status"])
        herdr_note = ""
        if herdr_rc == 0:
            oc_line = next((l for l in herdr_out.splitlines() if l.strip().startswith("opencode:")), "")
            herdr_note = f" ({oc_line.strip()})" if oc_line else ""
        return StageResult(
            "plugins", "fail",
            f"log shows '{_PLUGIN_FORMAT_ERROR}...'{herdr_note} -- "
            "the plugin predates opencode v2's plugin API (common cause: an "
            "outdated herdr install)",
            fix_command=(
                "herdr --version  # check current\n"
                "# upgrade herdr (read the installer first), then:\n"
                "herdr integration install opencode"
            ),
        )
    return StageResult("plugins", "ok", f"no plugin-format error in recent log; registered: {plugin_summary}")


def stage_5_service() -> StageResult:
    """opencode service status -- background service reachable."""
    rc, out = _run(["opencode", "service", "status"])
    if rc != 0 or not out.strip():
        return StageResult(
            "service", "warn", f"'opencode service status' unclear: {out[:150]}",
            fix_command="opencode service start",
        )
    return StageResult("service", "ok", out.strip().splitlines()[-1])


STAGES: list[Callable[[], StageResult]] = [
    stage_1_paths,
    stage_2_auth,
    stage_3_mcp,
    stage_4_plugins,
    stage_5_service,
]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


_STATUS_ICON = {"ok": "✓", "warn": "⚠", "fail": "✗", "skipped": "·"}


def print_report(results: list[StageResult]) -> int:
    print()
    print("OpenCode v2 Diagnostic")
    print("=" * 60)
    n_fail = n_warn = 0
    for r in results:
        icon = _STATUS_ICON.get(r.status, "?")
        print(f"  [{icon}] {r.name:<10} {r.detail}")
        if r.status in ("fail", "warn"):
            n_fail += 1 if r.status == "fail" else 0
            n_warn += 1 if r.status == "warn" else 0
            if r.fix_command:
                print(f"        fix: {r.fix_command}")
    print()
    if n_fail == 0 and n_warn == 0:
        print("✓ All opencode stages passed.")
        return 0
    if n_fail == 0:
        print(f"⚠ {n_warn} warning(s), no failures.")
        return 1
    print(f"✗ {n_fail} failure(s), {n_warn} warning(s). See 'fix:' lines above.")
    return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args()

    results: list[StageResult] = []
    for stage in STAGES:
        try:
            results.append(stage())
        except Exception as e:
            results.append(StageResult(stage.__name__, "fail", f"probe crashed: {type(e).__name__}: {str(e)[:120]}"))

    if args.json:
        print(json.dumps([{
            "name": r.name, "status": r.status, "detail": r.detail,
            "fix_command": r.fix_command,
        } for r in results], indent=2))
        n_fail = sum(1 for r in results if r.status == "fail")
        n_warn = sum(1 for r in results if r.status == "warn")
        return 1 if (n_fail or n_warn) else 0

    return print_report(results)


if __name__ == "__main__":
    sys.exit(main())
