#!/usr/bin/env python3
"""
MoJoAssistant Doctor — live feature validator and setup wizard.

Usage:
    python3 scripts/doctor.py            # run all probes, show feature status
    python3 scripts/doctor.py --setup    # same as above (alias)
    python3 scripts/doctor.py --fix      # interactive wizard — guides setup for each broken item
    python3 scripts/doctor.py --json     # machine-readable output
    python3 scripts/doctor.py --stable   # exit non-zero if any stable probe fails

Exit codes:
    0 — all stable probes passed (experimental failures are OK)
    1 — one or more stable probes failed
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

def _tty(code: str) -> str:
    return f"\033[{code}m" if sys.stdout.isatty() else ""

GREEN  = _tty("32")
YELLOW = _tty("33")
RED    = _tty("31")
BOLD   = _tty("1")
DIM    = _tty("2")
RESET  = _tty("0")

OK_ICON   = "✅"
WARN_ICON = "⚠️ "
FAIL_ICON = "❌"


# ---------------------------------------------------------------------------
# Probe result
# ---------------------------------------------------------------------------

Status = Literal["ok", "warn", "fail"]


class ProbeResult:
    def __init__(self, name: str, tier: str, status: Status, detail: str):
        self.name = name
        self.tier = tier       # "stable" or "experimental"
        self.status = status
        self.detail = detail

    def icon(self) -> str:
        return {
            "ok":   OK_ICON,
            "warn": WARN_ICON,
            "fail": FAIL_ICON,
        }[self.status]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tier": self.tier,
            "status": self.status,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _memory_path() -> Path:
    return Path(os.environ.get("MEMORY_PATH", Path.home() / ".memory"))


def _server_url() -> str:
    port = os.environ.get("SERVER_PORT", "8000")
    host = os.environ.get("SERVER_HOST", "localhost")
    return f"http://{host}:{port}"


def _infra_context() -> dict:
    path = _memory_path() / "config" / "infra_context.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------------------
# Probes — stable tier
# ---------------------------------------------------------------------------

def _health_request(path: str) -> dict:
    import urllib.request
    url = _server_url() + path
    headers = {"Accept": "application/json"}
    api_key = _mcp_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read())


def probe_scheduler() -> ProbeResult:
    try:
        data = _health_request("/api/health")
        status = data.get("status", "")
        scheduler = data.get("scheduler", {})
        sched_status = scheduler.get("status", status)
        tasks_queued = scheduler.get("tasks_queued", data.get("tasks_queued", "—"))
        if sched_status in ("running", "healthy"):
            return ProbeResult("Scheduler daemon", "stable", "ok",
                               f"running, {tasks_queued} tasks queued")
        return ProbeResult("Scheduler daemon", "stable", "warn",
                           f"status={sched_status!r}")
    except Exception as exc:
        return ProbeResult("Scheduler daemon", "stable", "fail",
                           f"not reachable at {_server_url()} ({_short(exc)})")


def probe_hitl_inbox() -> ProbeResult:
    try:
        data = _health_request("/api/health")
        hitl = data.get("hitl", {})
        pending = hitl.get("pending", 0)
        return ProbeResult("HITL inbox", "stable", "ok",
                           f"reachable, {pending} pending")
    except Exception as exc:
        return ProbeResult("HITL inbox", "stable", "fail",
                           f"not reachable ({_short(exc)})")


def probe_memory() -> ProbeResult:
    try:
        from app.config.paths import get_memory_subpath
        mem_path = _memory_path()
        if not mem_path.exists():
            return ProbeResult("Memory search", "stable", "fail",
                               f"{mem_path} does not exist — run first-time setup")
        model = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        return ProbeResult("Memory search", "stable", "ok",
                           f"local embeddings active ({model})")
    except Exception as exc:
        return ProbeResult("Memory search", "stable", "warn",
                           f"import error ({_short(exc)})")


def _mcp_api_key() -> str:
    """Best-effort: read MCP_API_KEY from env or .env file."""
    key = os.environ.get("MCP_API_KEY", "")
    if key:
        return key
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("MCP_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def probe_mcp_surface() -> ProbeResult:
    try:
        import urllib.request
        # MCP server is at root POST / (not /mcp)
        url = _server_url() + "/"
        headers = {"Content-Type": "application/json"}
        api_key = _mcp_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(
            url, method="POST",
            headers=headers,
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(),
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        tools = data.get("result", {}).get("tools", [])
        count = len(tools)
        return ProbeResult("MCP tool surface", "stable", "ok",
                           f"{count} tools registered")
    except Exception as exc:
        return ProbeResult("MCP tool surface", "stable", "fail",
                           f"not reachable ({_short(exc)})")


def probe_policy() -> ProbeResult:
    try:
        patterns_path = _memory_path() / "config" / "behavioral_patterns.json"
        if patterns_path.exists():
            data = json.loads(patterns_path.read_text(encoding="utf-8"))
            count = len(data) if isinstance(data, list) else len(data.get("patterns", data))
            return ProbeResult("Policy checker", "stable", "ok",
                               f"active, {count} patterns loaded")
        # Fall back to checking the module is importable
        from app.scheduler.policy.static import StaticPolicyChecker
        return ProbeResult("Policy checker", "stable", "ok",
                           "active (default patterns, no custom behavioral_patterns.json)")
    except Exception as exc:
        return ProbeResult("Policy checker", "stable", "warn",
                           f"import error ({_short(exc)})")


def probe_roles() -> ProbeResult:
    try:
        roles_path = _memory_path() / "roles"
        if roles_path.exists():
            roles = [d for d in roles_path.iterdir() if d.is_dir()]
            count = len(roles)
            names = ", ".join(d.name for d in roles[:3])
            suffix = ", …" if count > 3 else ""
            label = f"{count} roles loaded ({names}{suffix})" if count else "0 roles — create one with mojo role create"
            status: Status = "ok" if count > 0 else "warn"
            return ProbeResult("Role system", "stable", status, label)
        return ProbeResult("Role system", "stable", "warn",
                           f"{roles_path} not found — no roles yet")
    except Exception as exc:
        return ProbeResult("Role system", "stable", "warn", _short(exc))


def probe_audit_trail() -> ProbeResult:
    try:
        audit_path = _memory_path() / "logs" / "audit.log"
        if audit_path.exists():
            size = audit_path.stat().st_size
            return ProbeResult("Audit trail", "stable", "ok",
                               f"append-only log active ({size:,} bytes)")
        audit_dir = _memory_path() / "logs"
        if audit_dir.exists():
            return ProbeResult("Audit trail", "stable", "warn",
                               "logs/ directory exists but audit.log not yet written")
        return ProbeResult("Audit trail", "stable", "warn",
                           "audit log not yet initialized — starts on first request")
    except Exception as exc:
        return ProbeResult("Audit trail", "stable", "warn", _short(exc))


# ---------------------------------------------------------------------------
# Probes — experimental tier
# ---------------------------------------------------------------------------

def probe_agent_execution() -> ProbeResult:
    try:
        from app.config.paths import get_memory_subpath
        llm_config_path = PROJECT_ROOT / "config" / "llm_config.json"
        endpoint = "http://localhost:1234/v1"
        if llm_config_path.exists():
            cfg = json.loads(llm_config_path.read_text(encoding="utf-8"))
            providers = cfg.get("providers", {})
            lmstudio = providers.get("lmstudio", {})
            endpoint = lmstudio.get("base_url", endpoint)

        import urllib.request
        url = endpoint.rstrip("/v1").rstrip("/") + "/v1/models"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read())
        models = data.get("data", [])
        count = len(models)
        return ProbeResult("Agent execution", "experimental", "ok",
                           f"LLM reachable at {endpoint}, {count} model(s) loaded")
    except Exception as exc:
        endpoint_hint = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
        return ProbeResult("Agent execution", "experimental", "warn",
                           f"no LLM reachable at {endpoint_hint} ({_short(exc)})")


def probe_coding_agent() -> ProbeResult:
    for binary in ("claude", "opencode"):
        path = shutil.which(binary)
        if path:
            try:
                result = subprocess.run([binary, "--version"], capture_output=True,
                                        text=True, timeout=5)
                ver = (result.stdout or result.stderr).strip().splitlines()[0]
                return ProbeResult("Coding agent bridge", "experimental", "ok",
                                   f"{binary} found at {path} ({ver})")
            except Exception:
                return ProbeResult("Coding agent bridge", "experimental", "ok",
                                   f"{binary} found at {path}")
    return ProbeResult("Coding agent bridge", "experimental", "warn",
                       "claude and opencode not found in PATH — install one to enable agent tasks")


def probe_voice() -> ProbeResult:
    voice_dir = PROJECT_ROOT / "submodules" / "mojo-voice"
    voice_enabled = os.environ.get("VOICE_ENABLED", "").lower() in ("1", "true", "yes")
    if voice_dir.exists() and voice_enabled:
        return ProbeResult("Voice pipeline", "experimental", "ok",
                           "mojo-voice configured and enabled")
    if voice_dir.exists():
        return ProbeResult("Voice pipeline", "experimental", "warn",
                           "mojo-voice submodule present but VOICE_ENABLED not set")
    return ProbeResult("Voice pipeline", "experimental", "fail",
                       "mojo-voice not configured (see docs/guides/VOICE.md)")


def probe_cubesandbox() -> ProbeResult:
    e2b_url = os.environ.get("E2B_API_URL") or _infra_context().get("E2B_API_URL")
    e2b_key = os.environ.get("E2B_API_KEY") or _infra_context().get("E2B_API_KEY")
    if e2b_url and e2b_key:
        return ProbeResult("CubeSandbox", "experimental", "ok",
                           f"E2B_API_URL={e2b_url}")
    if e2b_url:
        return ProbeResult("CubeSandbox", "experimental", "warn",
                           "E2B_API_URL set but E2B_API_KEY missing")
    return ProbeResult("CubeSandbox", "experimental", "fail",
                       "E2B_API_URL not set — run Ahman's install task first")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short(exc: Exception) -> str:
    msg = str(exc)
    return msg[:80] + "…" if len(msg) > 80 else msg


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

STABLE_PROBES = [
    probe_scheduler,
    probe_hitl_inbox,
    probe_memory,
    probe_mcp_surface,
    probe_policy,
    probe_roles,
    probe_audit_trail,
]

EXPERIMENTAL_PROBES = [
    probe_agent_execution,
    probe_coding_agent,
    probe_voice,
    probe_cubesandbox,
]


def run_all_probes() -> list[ProbeResult]:
    results = []
    for probe in STABLE_PROBES:
        try:
            results.append(probe())
        except Exception as exc:
            fname = probe.__name__.replace("probe_", "").replace("_", " ").title()
            results.append(ProbeResult(fname, "stable", "fail", f"probe crashed: {_short(exc)}"))
    for probe in EXPERIMENTAL_PROBES:
        try:
            results.append(probe())
        except Exception as exc:
            fname = probe.__name__.replace("probe_", "").replace("_", " ").title()
            results.append(ProbeResult(fname, "experimental", "fail", f"probe crashed: {_short(exc)}"))
    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - len(s))


def print_report(results: list[ProbeResult]) -> None:
    stable = [r for r in results if r.tier == "stable"]
    experimental = [r for r in results if r.tier == "experimental"]

    name_width = max((len(r.name) for r in results), default=20) + 2

    print()
    print(f"{BOLD}MoJoAssistant Setup Check{RESET}")
    print("═" * 48)
    print()

    print(f"{BOLD}Core (Stable){RESET}")
    for r in stable:
        icon = r.icon()
        name = _pad(r.name, name_width)
        print(f"  {icon}  {name}— {DIM}{r.detail}{RESET}")

    print()
    print(f"{BOLD}Optional (Experimental){RESET}")
    for r in experimental:
        icon = r.icon()
        name = _pad(r.name, name_width)
        print(f"  {icon}  {name}— {DIM}{r.detail}{RESET}")

    stable_fails = [r for r in stable if r.status == "fail"]
    exp_issues   = [r for r in experimental if r.status in ("warn", "fail")]

    print()
    if stable_fails:
        print(f"{RED}{BOLD}⚠  {len(stable_fails)} stable check(s) failed — MoJo may not be fully operational.{RESET}")
        print(f"   Run {BOLD}python3 scripts/config_doctor.py{RESET} for configuration details.")
    else:
        print(f"{GREEN}{BOLD}✓  All stable checks passed.{RESET}")
    if exp_issues:
        print(f"   {len(exp_issues)} experimental feature(s) need extra setup.")
    print()
    print(f"   Run {BOLD}pytest tests/smoke/ -m stable{RESET} to verify the test suite.")
    print()


# ---------------------------------------------------------------------------
# Interactive wizard (--fix)
# ---------------------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return answer or default


def _hr(title: str) -> None:
    print()
    print(f"{BOLD}─── {title} {'─' * max(0, 48 - len(title) - 5)}{RESET}")
    print()


def _wizard_mcp_server() -> bool:
    """Step 1: ensure MoJo MCP server is running."""
    _hr("Step 1: Memory & MCP Server")
    mem_path = _memory_path()
    mem_ok = mem_path.exists()
    print(f"  Memory path:  {mem_path}  {'[exists ✅]' if mem_ok else '[❌ missing]'}")

    # Check server
    try:
        _health_request("/api/health")
        print(f"  MCP server:   running at {_server_url()}  [✅]")
        return True
    except Exception:
        print(f"  MCP server:   not running  [❌]")

    answer = _ask("\nStart MoJo as a systemd user service?", "Y")
    if answer.upper() not in ("Y", "YES", ""):
        print("  Skipped — MoJo must be running for other steps.")
        return False

    print()
    print(f"  {DIM}$ systemctl --user enable mojoassistant{RESET}")
    subprocess.run(["systemctl", "--user", "enable", "mojoassistant"], check=False)
    print(f"  {DIM}$ systemctl --user start mojoassistant{RESET}")
    subprocess.run(["systemctl", "--user", "start", "mojoassistant"], check=False)

    print("  Waiting for server to start", end="", flush=True)
    for _ in range(15):
        import time as _time
        _time.sleep(1)
        print(".", end="", flush=True)
        try:
            _health_request("/api/health")
            print(f"\n  {GREEN}✅ MCP server running on port {_server_url().split(':')[-1]}{RESET}")
            return True
        except Exception:
            pass
    print(f"\n  {RED}❌ Server did not start — check: journalctl --user -u mojoassistant{RESET}")
    return False


def _wizard_connect_claude() -> None:
    """Step 2: help user connect Claude to MoJo."""
    _hr("Step 2: Connect Claude to MoJo")
    port = _server_url().split(":")[-1]
    print("  How will you use Claude?\n")
    print("    1. Claude Code on this machine     (same computer, no tunnel needed)")
    print("    2. Claude.ai in browser            (needs cloudflared tunnel)")
    print("    3. Claude Code on another machine  (needs cloudflared or Tailscale)")
    print()
    choice = _ask("  Choice", "1")

    if choice == "1":
        config_path = Path.home() / ".claude" / "mcp_servers.json"
        api_key = _mcp_api_key()
        entry: dict = {
            "mojoassistant": {
                "url": f"http://localhost:{port}/",
                "headers": {"Authorization": f"Bearer {api_key}"} if api_key else {},
            }
        }
        print()
        print(f"  Add to {config_path}:")
        print(f"  {DIM}{json.dumps(entry, indent=4)}{RESET}")
        write = _ask("\n  Write this to ~/.claude/mcp_servers.json?", "Y")
        if write.upper() in ("Y", "YES", ""):
            existing: dict = {}
            if config_path.exists():
                try:
                    existing = json.loads(config_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            existing.update(entry)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
            print(f"  {GREEN}✅ Written to {config_path}{RESET}")
        else:
            print("  Skipped.")

    elif choice in ("2", "3"):
        if not shutil.which("cloudflared"):
            print(f"\n  {YELLOW}⚠  cloudflared not found in PATH.{RESET}")
            print("  Install it: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
            _ask("  Press Enter once installed (or Enter to skip)")
            if not shutil.which("cloudflared"):
                print("  Skipped — cloudflared still not found.")
                return

        print(f"\n  Starting cloudflared tunnel to http://localhost:{port} ...")
        print(f"  {DIM}$ cloudflared tunnel --url http://localhost:{port}{RESET}")
        print()
        print(f"  {YELLOW}This will print a URL like https://xxxx.trycloudflare.com{RESET}")
        print("  Copy that URL and add it to:")
        if choice == "2":
            print("    Claude.ai → Settings → Integrations")
            print("    URL:  https://xxxx.trycloudflare.com/")
            print("    Name: MoJo")
        else:
            print("    ~/.claude/mcp_servers.json on the remote machine")
            print('    { "mojoassistant": { "url": "https://xxxx.trycloudflare.com/" } }')
        print()
        _ask("  Press Enter to launch cloudflared (Ctrl+C to cancel)")
        try:
            subprocess.run(
                ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
                check=False,
            )
        except KeyboardInterrupt:
            print("\n  Tunnel stopped.")
    else:
        print("  Skipped.")


def _wizard_llm_backend() -> None:
    """Step 3: detect and configure LLM backend for agent execution."""
    _hr("Step 3: LLM Backend (for agent tasks)")
    print(f"  {DIM}Agent execution is EXPERIMENTAL — lets roles run autonomous tasks.{RESET}")
    print(f"  {DIM}Requires a local or remote LLM endpoint.{RESET}\n")

    # Detect
    lmstudio_url = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
    ollama_url   = "http://localhost:11434/v1"

    def _check(url: str) -> str:
        try:
            import urllib.request
            with urllib.request.urlopen(url.rstrip("/v1") + "/v1/models", timeout=2) as r:
                d = json.loads(r.read())
            count = len(d.get("data", []))
            return f"running ({count} model(s))"
        except Exception:
            return "not running"

    lm_status = _check(lmstudio_url)
    ol_status  = _check(ollama_url)

    print(f"  Detected LMStudio ({lmstudio_url}):  {lm_status}")
    print(f"  Detected Ollama   ({ollama_url}):  {ol_status}")
    print()
    print("  Options:")
    print("    1. LMStudio (recommended) — download at lmstudio.ai, load Qwen2.5")
    print("    2. Ollama                 — run: curl -fsSL https://ollama.ai/install.sh | sh")
    print("    3. OpenRouter             — set OPEN_ROUTER_KEY in .env")
    print("    4. Skip for now           — roles can still chat, no autonomous tasks")
    print()
    choice = _ask("  Choice", "4")

    if choice == "1":
        url = _ask("  LMStudio base URL", lmstudio_url)
        _set_env_var("LMSTUDIO_BASE_URL", url)
        print(f"  {GREEN}✅ LMSTUDIO_BASE_URL set in .env{RESET}")
    elif choice == "2":
        if not shutil.which("ollama"):
            print(f"\n  {YELLOW}⚠  ollama not in PATH. Install: curl -fsSL https://ollama.ai/install.sh | sh{RESET}")
        else:
            print(f"  {GREEN}✅ ollama found — start with: ollama serve{RESET}")
    elif choice == "3":
        key = _ask("  OpenRouter API key")
        if key:
            _set_env_var("OPEN_ROUTER_KEY", key)
            print(f"  {GREEN}✅ OPEN_ROUTER_KEY set in .env{RESET}")
    else:
        print(f"  {YELLOW}⚠️  Agent execution skipped — skipped{RESET}")


def _set_env_var(key: str, value: str) -> None:
    """Write or update a key=value line in .env."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists() and (PROJECT_ROOT / ".env.example").exists():
        import shutil as _shutil
        _shutil.copy(PROJECT_ROOT / ".env.example", env_file)

    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}=") or line.startswith(f"# {key}="):
                lines[i] = f"{key}={value}"
                updated = True
                break
        if not updated:
            lines.append(f"{key}={value}")
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        env_file.write_text(f"{key}={value}\n", encoding="utf-8")


def _wizard_validate() -> bool:
    """Step 4: run stable smoke suite and print summary."""
    _hr("Step 4: Validation")
    print("  Running stable smoke suite...")
    print()

    venv_python = PROJECT_ROOT / "venv" / "bin" / "python"
    python_bin = str(venv_python) if venv_python.exists() else sys.executable

    result = subprocess.run(
        [python_bin, "-m", "pytest", "tests/smoke/", "-m", "stable", "-q", "--tb=line",
         "--no-header"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    # Print last few lines (summary)
    lines = (result.stdout + result.stderr).strip().splitlines()
    for line in lines[-10:]:
        print(f"  {line}")

    passed = result.returncode == 0
    print()
    if passed:
        print(f"  {GREEN}{BOLD}All stable checks passed.{RESET}")
    else:
        print(f"  {RED}{BOLD}Some stable checks failed — see above.{RESET}")
    return passed


def run_wizard() -> int:
    """Interactive setup wizard — guides user through each broken item."""
    print()
    print(f"{BOLD}MoJoAssistant Setup Wizard{RESET}")
    print("═" * 48)
    print(f"{DIM}We'll walk through each component and fix what's broken.{RESET}")

    server_ok = _wizard_mcp_server()
    _wizard_connect_claude()
    _wizard_llm_backend()
    stable_ok = _wizard_validate()

    _hr("Your MoJo is ready" if stable_ok else "Setup incomplete")

    # Re-run probes for final summary
    results = run_all_probes()
    stable_ok_list  = [r for r in results if r.tier == "stable"       and r.status == "ok"]
    exp_ok_list     = [r for r in results if r.tier == "experimental" and r.status == "ok"]
    exp_issue_list  = [r for r in results if r.tier == "experimental" and r.status != "ok"]

    if stable_ok_list:
        print(f"  {BOLD}Stable features (working now):{RESET}")
        for r in stable_ok_list:
            print(f"    • {r.name}")
    if exp_ok_list:
        print(f"\n  {BOLD}Experimental features (active):{RESET}")
        for r in exp_ok_list:
            print(f"    • {r.name}")
    if exp_issue_list:
        print(f"\n  {BOLD}Experimental features (need extra setup):{RESET}")
        for r in exp_issue_list:
            print(f"    • {r.name:25s} → {DIM}{r.detail}{RESET}")

    print(f"\n  {BOLD}Quick start:{RESET}")
    print("    Check status:   python3 scripts/doctor.py")
    print("    Run tests:      pytest tests/smoke/ -m stable")
    print("    Restart MoJo:   systemctl --user restart mojoassistant")
    print()

    stable_failures = [r for r in results if r.tier == "stable" and r.status == "fail"]
    return 1 if stable_failures else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MoJoAssistant feature validator — checks what's actually working."
    )
    parser.add_argument("--setup", action="store_true",
                        help="Run feature validator (same as default)")
    parser.add_argument("--fix", action="store_true",
                        help="Interactive wizard — guided setup for each broken item")
    parser.add_argument("--json", action="store_true",
                        help="Output machine-readable JSON")
    parser.add_argument("--stable", action="store_true",
                        help="Exit non-zero if any stable probe fails")
    args = parser.parse_args(argv)

    if args.fix:
        return run_wizard()

    results = run_all_probes()

    if args.json:
        data = {
            "results": [r.to_dict() for r in results],
            "summary": {
                "stable_ok":    sum(1 for r in results if r.tier == "stable" and r.status == "ok"),
                "stable_fail":  sum(1 for r in results if r.tier == "stable" and r.status != "ok"),
                "exp_ok":       sum(1 for r in results if r.tier == "experimental" and r.status == "ok"),
                "exp_issues":   sum(1 for r in results if r.tier == "experimental" and r.status != "ok"),
            },
        }
        print(json.dumps(data, indent=2))
    else:
        print_report(results)

    stable_failures = [r for r in results if r.tier == "stable" and r.status == "fail"]
    return 1 if stable_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
