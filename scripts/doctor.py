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


def _mcp_servers_config() -> dict:
    """Load merged MCP servers config: project default + personal override."""
    servers: dict = {}
    for path in [
        PROJECT_ROOT / "config" / "mcp_servers.json",
        _memory_path() / "config" / "mcp_servers.json",
    ]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for s in data.get("servers", []):
                    servers[s["id"]] = s
            except Exception:
                pass
    return servers


def probe_capability_coverage() -> ProbeResult:
    """Check that every capability declared by any role is backed by real tools."""
    try:
        # Capabilities wired directly — no external server needed
        WIRED_CAPABILITIES = {
            "knowledge", "file", "exec", "web", "comms", "orchestration", "memory",
        }
        # Capabilities backed by external MCP servers — check config + binary
        REQUIRES_MCP = {
            "terminal": ("tmux MCP server", "tmux-mcp-rs", "~/.cargo/bin/tmux-mcp-rs"),
            "browser":  ("Playwright MCP server", "npx", None),
            "google":   ("Google Workspace MCP server", None, None),
        }

        mcp_servers = _mcp_servers_config()
        # Map category → whether a server is configured+enabled for it
        category_has_server: dict[str, bool] = {}
        for srv in mcp_servers.values():
            cat = srv.get("category")
            enabled = srv.get("enabled", True)
            if cat and enabled:
                # Check required binary exists
                requires = srv.get("requires", [])
                binary_ok = True
                for req in requires:
                    if req.get("manual"):
                        continue
                    binary = req.get("binary", "")
                    if not shutil.which(binary):
                        # Check ~/.cargo/bin as fallback
                        cargo_path = Path.home() / ".cargo" / "bin" / binary
                        if not cargo_path.exists():
                            binary_ok = False
                            break
                if binary_ok:
                    category_has_server[cat] = True

        roles_path = _memory_path() / "roles"
        phantom: list[str] = []   # capability declared but no backing

        if roles_path.exists():
            for role_file in roles_path.glob("*.json"):
                try:
                    role = json.loads(role_file.read_text())
                    caps = set(role.get("capabilities") or [])
                    role_id = role.get("id") or role_file.stem
                    for cap in caps:
                        if cap in WIRED_CAPABILITIES:
                            continue
                        if cap in REQUIRES_MCP:
                            if not category_has_server.get(cap):
                                label, binary, alt_path = REQUIRES_MCP[cap]
                                # Check alt path (e.g. ~/.cargo/bin)
                                alt_ok = alt_path and Path(alt_path.replace("~", str(Path.home()))).exists()
                                if not alt_ok:
                                    phantom.append(f"{role_id}:{cap} (needs {label})")
                except Exception:
                    pass

        if phantom:
            # Deduplicate by capability
            by_cap: dict[str, list[str]] = {}
            for item in phantom:
                role_id, rest = item.split(":", 1)
                cap = rest.split(" ")[0]
                by_cap.setdefault(cap, []).append(role_id)
            msg = "; ".join(
                f"{cap} missing for: {', '.join(roles)} — {REQUIRES_MCP[cap][0]}"
                for cap, roles in by_cap.items()
            )
            return ProbeResult("Capability coverage", "stable", "warn", msg)

        return ProbeResult("Capability coverage", "stable", "ok",
                           "all declared capabilities are backed by configured tools")
    except Exception as exc:
        return ProbeResult("Capability coverage", "stable", "warn", _short(exc))


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

def _detect_gpu() -> dict:
    """Return GPU info: vendor, vram_gb, count."""
    import urllib.request as _ur
    # NVIDIA
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            gpus = [line.split(",") for line in r.stdout.strip().splitlines()]
            vram_mb = sum(int(g[1].strip().split()[0]) for g in gpus if len(g) > 1)
            return {"vendor": "nvidia", "vram_gb": round(vram_mb / 1024), "count": len(gpus),
                    "names": [g[0].strip() for g in gpus]}
    except Exception:
        pass
    # AMD ROCm
    try:
        r = subprocess.run(["rocm-smi", "--showmeminfo", "vram", "--csv"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            lines = [l for l in r.stdout.splitlines() if "Total" in l or "total" in l]
            vram_b = sum(int(l.split(",")[-1].strip()) for l in lines if l.split(",")[-1].strip().isdigit())
            if vram_b:
                return {"vendor": "amd", "vram_gb": round(vram_b / 1024**3), "count": len(lines),
                        "names": [f"AMD GPU {i}" for i in range(len(lines))]}
        # fallback: rocm-smi without csv
        r2 = subprocess.run(["rocm-smi", "--showmeminfo", "vram"],
                            capture_output=True, text=True, timeout=5)
        total_bytes = sum(
            int(l.split(":")[-1].strip())
            for l in r2.stdout.splitlines() if "Total Memory" in l and l.split(":")[-1].strip().isdigit()
        )
        if total_bytes:
            count = sum(1 for l in r2.stdout.splitlines() if "Total Memory" in l)
            return {"vendor": "amd", "vram_gb": round(total_bytes / 1024**3), "count": count,
                    "names": [f"AMD GPU {i}" for i in range(count)]}
    except Exception:
        pass
    return {"vendor": "none", "vram_gb": 0, "count": 0, "names": []}


def _infer_modalities(model_ids: list[str]) -> list[str]:
    """Infer what modalities a model likely supports from its name. Returns sorted list."""
    HINTS: list[tuple[str, list[str]]] = [
        ("text",      ["instruct", "chat", "qwen", "llama", "mistral", "gemma", "phi", "deepseek",
                        "gpt", "claude", "hermes", "yi-", "solar", "smollm", "internlm"]),
        ("vision",    ["vl", "vision", "visual", "llava", "internvl", "qwen-vl", "minicpm-v",
                        "molmo", "pixtral", "idefics", "paligemma", "cogvlm"]),
        ("audio",     ["whisper", "audio", "speech", "tts", "asr", "s2s", "voice", "qwen-audio",
                        "seamless", "salmonn", "wavllm"]),
        ("embedding", ["embed", "e5-", "bge-", "gte-", "nomic-embed", "stella", "rerank"]),
        ("thinking",  ["thinking", "r1", "qwq", "deepseek-r", "o1", "o3", "sky-t1"]),
        ("tools",     ["instruct", "hermes", "qwen", "llama", "mistral"]),  # broad — most instruct models support tools
    ]
    found: set[str] = set()
    for mid in model_ids:
        mid_lower = mid.lower()
        for modality, keywords in HINTS:
            if any(kw in mid_lower for kw in keywords):
                found.add(modality)
    # If we detected vision or audio but not text, also add text (multimodal models include text)
    if ("vision" in found or "audio" in found) and "text" not in found:
        found.add("text")
    return sorted(found)


def _detect_llm_runtimes() -> list[dict]:
    """Probe known LLM runtime endpoints. Returns list of dicts with id/url/status/models."""
    import urllib.request
    RUNTIMES = [
        {"id": "lmstudio",  "label": "LM Studio",      "url": os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),  "models_path": "/v1/models",     "models_key": "data"},
        {"id": "ollama",    "label": "Ollama",          "url": "http://localhost:11434",                                          "models_path": "/api/tags",      "models_key": "models"},
        {"id": "vllm",      "label": "vLLM",            "url": "http://localhost:8000/v1",                                        "models_path": "/v1/models",     "models_key": "data",  "text_llm_only": True},
        {"id": "lmdeploy",  "label": "LMDeploy",        "url": "http://localhost:23333/v1",                                       "models_path": "/v1/models",     "models_key": "data"},
        {"id": "sglang",    "label": "SGLang",          "url": "http://localhost:30000/v1",                                       "models_path": "/v1/models",     "models_key": "data"},
        {"id": "tabbyapi",  "label": "TabbyAPI",        "url": "http://localhost:5000/v1",                                        "models_path": "/v1/models",     "models_key": "data"},
    ]
    results = []
    for rt in RUNTIMES:
        base = rt["url"].rstrip("/v1").rstrip("/")
        probe_url = base + rt["models_path"]
        try:
            with urllib.request.urlopen(probe_url, timeout=2) as resp:
                data = json.loads(resp.read())
            models = data.get(rt["models_key"], [])
            model_ids = [m.get("id") or m.get("name") or str(m) for m in models[:3]]
            # Detect modalities from model IDs — modern models are often multimodal
            modalities = _infer_modalities(model_ids)
            has_text = "text" in modalities or not modalities  # unknown → assume text capable
            results.append({"id": rt["id"], "label": rt["label"], "url": rt["url"],
                            "status": "running", "model_count": len(models),
                            "models": model_ids, "modalities": modalities,
                            "is_text_llm": has_text})
        except Exception as e:
            err = str(e)
            auth_error = any(h in err for h in ("401", "403", "Invalid or missing API key", "authentication_error", "Unauthorized"))
            results.append({"id": rt["id"], "label": rt["label"], "url": rt["url"],
                            "status": "auth_protected" if auth_error else "offline",
                            "model_count": 0, "models": [], "modalities": [], "is_text_llm": None})
    # Unsloth Studio (not an API server — detect by install path)
    unsloth_data = Path.home() / ".local" / "share" / "unsloth"
    if unsloth_data.exists() and (unsloth_data / "launch-studio.sh").exists():
        results.append({"id": "unsloth", "label": "Unsloth Studio",
                        "url": str(unsloth_data / "launch-studio.sh"),
                        "status": "installed", "model_count": 0, "models": []})
    return results


def _detect_external_apis() -> dict[str, str]:
    """Return external LLM API keys found in env or .env file."""
    env_file = PROJECT_ROOT / ".env"
    env_vars: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()

    KEYS = {
        "OPEN_ROUTER_KEY":    "OpenRouter",
        "OPENROUTER_API_KEY": "OpenRouter",
        "OPENAI_API_KEY":     "OpenAI",
        "ANTHROPIC_API_KEY":  "Anthropic",
        "GEMINI_API_KEY":     "Gemini",
    }
    found = {}
    for key, label in KEYS.items():
        val = os.environ.get(key) or env_vars.get(key, "")
        if val and label not in found:
            found[label] = key
    return found


def _hardware_tier(vram_gb: int, ram_gb: int) -> tuple[str, str]:
    """Return (tier_id, description) based on hardware."""
    if vram_gb >= 48:
        return "workstation", f"workstation GPU ({vram_gb}GB VRAM) — can run 70B+ models"
    if vram_gb >= 20:
        return "large_gpu",   f"large GPU ({vram_gb}GB VRAM) — can run 30B–70B models"
    if vram_gb >= 10:
        return "mid_gpu",     f"mid GPU ({vram_gb}GB VRAM) — can run 7B–13B models"
    if vram_gb >= 4:
        return "small_gpu",   f"small GPU ({vram_gb}GB VRAM) — can run 3B–7B models (quantized)"
    if ram_gb >= 16:
        return "cpu_capable", f"CPU-only ({ram_gb}GB RAM) — can run small quantized models slowly"
    return "cpu_limited",     f"CPU-only ({ram_gb}GB RAM) — limited; use external API"


def probe_agent_execution() -> ProbeResult:
    """Detect all local LLM runtimes and external APIs."""
    try:
        runtimes = _detect_llm_runtimes()
        running = [r for r in runtimes if r["status"] in ("running", "auth_protected")]
        loaded  = [r for r in running if r["model_count"] > 0 and r.get("is_text_llm", True)]
        installed_only = [r for r in runtimes if r["status"] in ("installed",)]

        if loaded:
            summary = "; ".join(
                f"{r['label']} ({r['model_count']} model{'s' if r['model_count'] != 1 else ''})"
                for r in loaded
            )
            return ProbeResult("Agent execution (LLM)", "experimental", "ok", summary)

        if running:
            auth_protected = [r for r in running if r["status"] == "auth_protected"]
            no_models      = [r for r in running if r["status"] == "running" and r["model_count"] == 0]
            parts = []
            if auth_protected:
                parts.append(f"{', '.join(r['label'] for r in auth_protected)} running (auth-protected, modality unknown — may already serve text/vision/audio)")
            if no_models:
                parts.append(f"{', '.join(r['label'] for r in no_models)} running but no models loaded")
            return ProbeResult("Agent execution (LLM)", "experimental", "warn", "; ".join(parts))

        external = _detect_external_apis()
        if external:
            keys = ", ".join(external.keys())
            return ProbeResult("Agent execution (LLM)", "experimental", "warn",
                               f"no local LLM running — external API available: {keys} (usable as fallback brain)")

        if installed_only:
            names = ", ".join(r["label"] for r in installed_only)
            return ProbeResult("Agent execution (LLM)", "experimental", "warn",
                               f"{names} installed but not running — launch it to enable agent tasks")

        return ProbeResult("Agent execution (LLM)", "experimental", "fail",
                           "no local LLM detected and no external API keys — run --fix for setup guidance")
    except Exception as exc:
        return ProbeResult("Agent execution (LLM)", "experimental", "warn", _short(exc))


def probe_hardware() -> ProbeResult:
    """Report hardware capability tier for local LLM inference."""
    try:
        gpu = _detect_gpu()
        ram_kb = 0
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal"):
                    ram_kb = int(line.split()[1])
                    break
        except Exception:
            pass
        ram_gb = round(ram_kb / 1024 / 1024)
        tier_id, description = _hardware_tier(gpu["vram_gb"], ram_gb)

        gpu_label = f"{gpu['vendor'].upper()} {gpu['vram_gb']}GB VRAM" if gpu["vram_gb"] else "no GPU"
        detail = f"{gpu_label}, {ram_gb}GB RAM — {description}"
        status: Status = "ok" if tier_id not in ("cpu_limited",) else "warn"
        return ProbeResult("Hardware capability", "experimental", status, detail)
    except Exception as exc:
        return ProbeResult("Hardware capability", "experimental", "warn", _short(exc))


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
# Probes — external tools tier
# (third-party installs users need to be aware of)
# ---------------------------------------------------------------------------

def probe_opencode() -> ProbeResult:
    path = shutil.which("opencode")
    if path:
        try:
            r = subprocess.run(["opencode", "--version"], capture_output=True, text=True, timeout=5)
            ver = (r.stdout or r.stderr).strip().splitlines()[0]
            return ProbeResult("OpenCode", "tools", "ok", f"found at {path} ({ver})")
        except Exception:
            return ProbeResult("OpenCode", "tools", "ok", f"found at {path}")
    return ProbeResult(
        "OpenCode", "tools", "warn",
        "not installed — coding agent tasks need it  "
        "(npm install -g opencode-ai  or  https://opencode.ai)",
    )


def probe_chatmcp() -> ProbeResult:
    # ChatMCP is typically an Electron/desktop app; check common install locations
    candidates = [
        shutil.which("chatmcp"),
        shutil.which("chat-mcp"),
        # Homebrew / standard Linux locations
        Path.home() / ".local" / "bin" / "chatmcp",
        Path("/usr/local/bin/chatmcp"),
        # AppImage drop location users commonly use
        Path.home() / "Applications" / "ChatMCP.AppImage",
        Path.home() / "Desktop" / "ChatMCP.AppImage",
    ]
    for c in candidates:
        if c and Path(str(c)).exists():
            return ProbeResult("ChatMCP", "tools", "ok",
                               f"found at {c}  (MCP inspector/tester)")
    return ProbeResult(
        "ChatMCP", "tools", "warn",
        "not found — useful for testing MCP tool calls interactively  "
        "(https://github.com/AvengerMoJo/chatmcp/releases)",
    )


def probe_huggingface_token() -> ProbeResult:
    # Check env vars first, then ~/.huggingface/token, then ~/.cache/huggingface/token
    token = (
        os.environ.get("HUGGINGFACE_TOKEN")
        or os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    )
    if not token:
        for p in [
            Path.home() / ".huggingface" / "token",
            Path.home() / ".cache" / "huggingface" / "token",
        ]:
            if p.exists():
                token = p.read_text(encoding="utf-8").strip()
                break

    if token and len(token) > 8:
        masked = token[:4] + "…" + token[-4:]
        return ProbeResult("HuggingFace token", "tools", "ok",
                           f"token found ({masked}) — private models accessible")
    return ProbeResult(
        "HuggingFace token", "tools", "warn",
        "HF_TOKEN not set — public embedding models work, private/gated ones need a token  "
        "(huggingface.co/settings/tokens → write to ~/.huggingface/token)",
    )


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
    probe_capability_coverage,
    probe_audit_trail,
]

EXPERIMENTAL_PROBES = [
    probe_hardware,
    probe_agent_execution,
    probe_coding_agent,
    probe_voice,
    probe_cubesandbox,
]

TOOLS_PROBES = [
    probe_opencode,
    probe_chatmcp,
    probe_huggingface_token,
]


def run_all_probes() -> list[ProbeResult]:
    results = []
    for tier, probes in [("stable", STABLE_PROBES), ("experimental", EXPERIMENTAL_PROBES), ("tools", TOOLS_PROBES)]:
        for probe in probes:
            try:
                results.append(probe())
            except Exception as exc:
                fname = probe.__name__.replace("probe_", "").replace("_", " ").title()
                results.append(ProbeResult(fname, tier, "fail", f"probe crashed: {_short(exc)}"))
    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - len(s))


def print_report(results: list[ProbeResult]) -> None:
    stable       = [r for r in results if r.tier == "stable"]
    experimental = [r for r in results if r.tier == "experimental"]
    tools        = [r for r in results if r.tier == "tools"]

    name_width = max((len(r.name) for r in results), default=20) + 2

    print()
    print(f"{BOLD}MoJoAssistant Setup Check{RESET}")
    print("═" * 48)
    print()

    print(f"{BOLD}Core (Stable){RESET}")
    for r in stable:
        print(f"  {r.icon()}  {_pad(r.name, name_width)}— {DIM}{r.detail}{RESET}")

    print()
    print(f"{BOLD}Optional (Experimental){RESET}")
    for r in experimental:
        print(f"  {r.icon()}  {_pad(r.name, name_width)}— {DIM}{r.detail}{RESET}")

    print()
    print(f"{BOLD}External Tools{RESET}")
    for r in tools:
        print(f"  {r.icon()}  {_pad(r.name, name_width)}— {DIM}{r.detail}{RESET}")

    stable_fails = [r for r in stable if r.status == "fail"]
    exp_issues   = [r for r in experimental if r.status in ("warn", "fail")]
    tool_missing = [r for r in tools if r.status != "ok"]

    print()
    if stable_fails:
        print(f"{RED}{BOLD}⚠  {len(stable_fails)} stable check(s) failed — MoJo may not be fully operational.{RESET}")
        print(f"   Run {BOLD}python3 scripts/config_doctor.py{RESET} for configuration details.")
    else:
        print(f"{GREEN}{BOLD}✓  All stable checks passed.{RESET}")
    if exp_issues:
        print(f"   {len(exp_issues)} experimental feature(s) need extra setup.")
    if tool_missing:
        print(f"   {len(tool_missing)} external tool(s) not installed — run {BOLD}--fix{RESET} for install hints.")
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
    """Step 3: detect hardware + all LLM runtimes, guide user to a working brain."""
    _hr("Step 3: AI Brain (LLM for agent tasks)")
    print(f"  {DIM}Agent execution requires a local or external LLM. We'll find the best option for you.{RESET}\n")

    # --- Hardware ---
    gpu = _detect_gpu()
    ram_kb = 0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                ram_kb = int(line.split()[1])
                break
    except Exception:
        pass
    ram_gb = round(ram_kb / 1024 / 1024)
    tier_id, tier_desc = _hardware_tier(gpu["vram_gb"], ram_gb)

    gpu_label = (f"{gpu['vendor'].upper()} {gpu['vram_gb']}GB VRAM"
                 if gpu["vram_gb"] else "no dedicated GPU")
    print(f"  Hardware:  {gpu_label}, {ram_gb}GB RAM")
    print(f"  Tier:      {tier_desc}")
    print()

    # --- Local runtimes ---
    runtimes = _detect_llm_runtimes()
    running  = [r for r in runtimes if r["status"] == "running"]
    loaded   = [r for r in running  if r["model_count"] > 0]
    offline  = [r for r in runtimes if r["status"] == "offline"]
    installed_only = [r for r in runtimes if r["status"] == "installed"]

    print("  Local runtimes detected:")
    for rt in runtimes:
        if rt["status"] == "running" and rt["model_count"] > 0:
            models_str = ", ".join(rt["models"][:2]) or "—"
            modalities = rt.get("modalities", [])
            mod_str = f" [{', '.join(modalities)}]" if modalities else ""
            icon = OK_ICON
            note = f"running — {rt['model_count']} model(s): {models_str}{mod_str}"
        elif rt["status"] == "auth_protected":
            icon = WARN_ICON
            note = "running (auth-protected — modality unknown, may be text/vision/audio/speech/embedding)"
        elif rt["status"] == "running":
            icon = WARN_ICON
            note = "running but NO models loaded"
        elif rt["status"] == "installed":
            icon = WARN_ICON
            note = f"installed at {rt['url']} (not running)"
        else:
            icon = "  "
            note = "not detected"
        print(f"    {icon}  {rt['label']:20s} {DIM}{note}{RESET}")
    print()

    # --- External APIs ---
    external = _detect_external_apis()
    if external:
        print("  External API keys found:")
        for label, key in external.items():
            print(f"    {OK_ICON}  {label}  {DIM}(${key}){RESET}")
        print()

    # --- Already good? ---
    if loaded:
        print(f"  {GREEN}{BOLD}✅ Local LLM is ready — agent tasks can run now.{RESET}")
        print()
        print("  To register a runtime in llm_config.json, choose:")
        for rt in loaded:
            print(f"    • {rt['label']}: {rt['url']}")
        choice = _ask("\n  Auto-register the first working runtime in llm_config.json?", "Y")
        if choice.upper() in ("Y", "YES", ""):
            _register_llm_runtime(loaded[0])
        return

    # --- Nothing working — decide path ---
    if external and not running:
        print(f"  {YELLOW}No local LLM running. You have external API access — we can use that")
        print(f"  as a temporary brain to guide the local installation.{RESET}\n")
    elif not running and not external:
        print(f"  {RED}No local LLM and no external API key found.{RESET}")
        print("  We'll register a free external service so you have a brain to work with.\n")

    # --- Guidance by tier ---
    print(f"  {BOLD}Recommended setup for your hardware:{RESET}")
    if tier_id == "workstation":
        print("    Your GPU can run large models (30B–70B+).")
        print("    Recommended runtimes:")
        vllm_running = any(r["id"] == "vllm" and r["status"] == "running" for r in runtimes)
        print(f"      • vLLM      — fast inference{' (running ' + WARN_ICON + ' no models loaded)' if vllm_running else ''}")
        print("        Load a model: vllm serve Qwen/Qwen2.5-72B-Instruct-AWQ --max-model-len 8192")
        print("      • LM Studio — GUI-based, easy model switching (lmstudio.ai)")
        print("      • Unsloth Studio — fine-tuning + inference (~/.local/share/unsloth/)")
    elif tier_id == "large_gpu":
        print("    Your GPU can run 13B–30B models.")
        print("    Recommended: LM Studio (lmstudio.ai) or Ollama with Qwen2.5-14B")
    elif tier_id == "mid_gpu":
        print("    Your GPU can run 7B–13B models well.")
        print("    Recommended: LM Studio or Ollama with Qwen2.5-7B / Llama3.1-8B")
    elif tier_id == "small_gpu":
        print("    Your GPU can run small quantized models (3B–7B).")
        print("    Recommended: Ollama with Qwen2.5-3B-Q4 or Phi-3-mini")
    elif tier_id == "cpu_capable":
        print("    CPU-only inference is possible but slow.")
        print("    Recommended: Ollama with Qwen2.5-1.5B-Q4 or use OpenRouter as primary brain.")
    else:
        print("    Limited CPU-only. Recommend using OpenRouter or Anthropic API as primary brain.")
    print()

    print("  What would you like to do?\n")
    options = []
    if any(r["id"] == "vllm" and r["status"] == "running" for r in runtimes):
        options.append(("L", "Load a model into vLLM (already running on port 8000)"))
    if shutil.which("ollama"):
        options.append(("O", "Start Ollama + pull a recommended model"))
    options.append(("S", "Install LM Studio (GUI, easiest) — lmstudio.ai"))
    if tier_id in ("workstation", "large_gpu", "mid_gpu"):
        options.append(("V", "Install vLLM (fastest server-mode inference)"))
    if shutil.which(str(Path.home() / ".local/share/unsloth/launch-studio.sh")) or \
            (Path.home() / ".local/share/unsloth/launch-studio.sh").exists():
        options.append(("U", "Launch Unsloth Studio (already installed)"))
    options.append(("R", "Use OpenRouter as external brain (free tier available)"))
    options.append(("X", "Skip for now"))

    for key, desc in options:
        print(f"    {BOLD}{key}{RESET}) {desc}")
    print()
    choice = _ask("  Choice", "X").upper()

    if choice == "L":
        model = _ask("  Model to load (HuggingFace ID)",
                     "Qwen/Qwen2.5-72B-Instruct-AWQ" if tier_id == "workstation" else "Qwen/Qwen2.5-7B-Instruct-AWQ")
        print(f"\n  Run this to load the model into vLLM:")
        print(f"    {BOLD}$ vllm serve {model} --max-model-len 8192{RESET}")
        print(f"  Then restart doctor to verify.")
        _set_env_var("VLLM_BASE_URL", "http://localhost:8000/v1")

    elif choice == "O":
        model = _ask("  Ollama model to pull",
                     "qwen2.5:7b" if tier_id in ("mid_gpu", "large_gpu", "workstation") else "qwen2.5:3b")
        print(f"\n  {DIM}$ ollama serve &{RESET}")
        print(f"  {DIM}$ ollama pull {model}{RESET}")
        yn = _ask("  Run these now?", "Y")
        if yn.upper() in ("Y", "YES", ""):
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            subprocess.run(["ollama", "pull", model], check=False)

    elif choice == "S":
        print("\n  Download LM Studio from: https://lmstudio.ai")
        print("  After installing, load a model and start the local server (port 1234).")
        print("  Then run doctor again — it will auto-detect it.")

    elif choice == "V":
        print("\n  Install vLLM (ROCm/AMD):")
        print(f"    {BOLD}$ pip install vllm --extra-index-url https://download.pytorch.org/whl/rocm6.2{RESET}")
        print("  Or see: https://docs.vllm.ai/en/latest/getting_started/amd-installation.html")

    elif choice == "U":
        launch = Path.home() / ".local/share/unsloth/launch-studio.sh"
        print(f"\n  Launching Unsloth Studio...")
        print(f"  {DIM}$ bash {launch}{RESET}")
        yn = _ask("  Launch now?", "Y")
        if yn.upper() in ("Y", "YES", ""):
            subprocess.Popen(["bash", str(launch)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("  Unsloth Studio launching in background.")

    elif choice == "R":
        existing_key = os.environ.get("OPEN_ROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY", "")
        if existing_key:
            print(f"  {GREEN}✅ OpenRouter key already set.{RESET}")
        else:
            print("\n  Get a free API key at: https://openrouter.ai (no credit card needed for free tier)")
            key = _ask("  Paste your OpenRouter API key (or Enter to skip)")
            if key:
                _set_env_var("OPEN_ROUTER_KEY", key)
                print(f"  {GREEN}✅ OPEN_ROUTER_KEY saved to .env{RESET}")
    else:
        print(f"  {YELLOW}Skipped — run --fix again once you have a runtime ready.{RESET}")


def _register_llm_runtime(runtime: dict) -> None:
    """Write a detected runtime's URL into llm_config.json."""
    llm_config_path = PROJECT_ROOT / "config" / "llm_config.json"
    cfg: dict = {}
    if llm_config_path.exists():
        try:
            cfg = json.loads(llm_config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    rid = runtime["id"]
    providers = cfg.setdefault("providers", {})
    providers.setdefault(rid, {})["base_url"] = runtime["url"]
    providers[rid]["enabled"] = True
    llm_config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print(f"  {GREEN}✅ {runtime['label']} registered in llm_config.json (base_url={runtime['url']}){RESET}")


def _wizard_mcp_resource_pool() -> None:
    """Step 4b: show MCP server status and guide user through enabling them."""
    _hr("Step 4b: MCP Servers & Resource Pool")
    print(f"  {DIM}MCP servers extend what agents can do — browser, terminal, Google Workspace, etc.{RESET}\n")

    mcp_servers = _mcp_servers_config()
    if not mcp_servers:
        print(f"  {WARN_ICON}  No MCP servers configured. Edit config/mcp_servers.json to add servers.\n")
        return

    for srv_id, srv in mcp_servers.items():
        name     = srv.get("name", srv_id)
        enabled  = srv.get("enabled", True)
        category = srv.get("category", "?")
        transport = srv.get("transport", "?")
        requires = srv.get("requires", [])

        # Check binaries
        missing_bins = []
        for req in requires:
            if req.get("manual"):
                continue
            binary = req.get("binary", "")
            found = shutil.which(binary) or (Path.home() / ".cargo" / "bin" / binary).exists()
            if not found:
                missing_bins.append(binary)

        if not enabled:
            icon, note = "  ", "disabled"
        elif missing_bins:
            icon, note = FAIL_ICON, f"missing: {', '.join(missing_bins)}"
        else:
            icon, note = OK_ICON, f"ready ({transport}, category={category})"

        print(f"  {icon}  {name:30s} {DIM}{note}{RESET}")
        if srv.get("install_hint") and missing_bins:
            print(f"       {DIM}Install: {srv['install_hint']}{RESET}")

    print()
    print(f"  {DIM}Personal overrides: ~/.memory/config/mcp_servers.json{RESET}")
    print(f"  {DIM}To enable a disabled server, set \"enabled\": true in config/mcp_servers.json{RESET}")
    print()


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


def _wizard_external_tools() -> None:
    """Step 4: inform user about external tools they should install."""
    _hr("Step 4: External Tools")
    print(f"  {DIM}These tools aren't part of MoJo itself but make it much more useful.{RESET}\n")

    sections = [
        {
            "name": "OpenCode",
            "probe": probe_opencode,
            "why": "Lets MoJo spawn a coding agent to write, edit, and run code as a scheduler task.",
            "install": [
                "npm install -g opencode-ai",
                "# or download from https://opencode.ai",
            ],
        },
        {
            "name": "ChatMCP",
            "probe": probe_chatmcp,
            "why": "Desktop client for testing MCP tool calls interactively — great for verifying your MoJo tools work before using Claude.",
            "install": [
                "# Download AppImage / installer from:",
                "# https://github.com/AvengerMoJo/chatmcp/releases",
                "#",
                "# After installing, add MoJo as an MCP server:",
                "#   URL:  http://localhost:8000/",
                "#   Name: MoJoAssistant",
                "#   Auth: Bearer <your MCP_API_KEY from .env>",
            ],
        },
        {
            "name": "HuggingFace token",
            "probe": probe_huggingface_token,
            "why": "Required for gated/private embedding models. Public models (all-MiniLM-L6-v2, BAAI/bge-m3) work without a token.",
            "install": [
                "# 1. Create account at https://huggingface.co",
                "# 2. Go to https://huggingface.co/settings/tokens",
                "# 3. Create a Read token, then:",
                "huggingface-cli login",
                "# or: echo 'hf_yourtoken' > ~/.huggingface/token",
            ],
        },
    ]

    for s in sections:
        result = s["probe"]()
        icon = result.icon()
        status_line = f"{BOLD}{s['name']}{RESET}  {icon}  {DIM}{result.detail}{RESET}"
        print(f"  {status_line}")
        print(f"  {DIM}Why: {s['why']}{RESET}")

        if result.status != "ok":
            show = _ask(f"\n  Show install instructions for {s['name']}?", "Y")
            if show.upper() in ("Y", "YES", ""):
                print()
                for line in s["install"]:
                    if line.startswith("#"):
                        print(f"    {DIM}{line}{RESET}")
                    else:
                        print(f"    {BOLD}$ {line}{RESET}")
        print()


def _wizard_validate() -> bool:
    """Step 5: run stable smoke suite and print summary."""
    _hr("Step 5: Validation")
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
    _wizard_mcp_resource_pool()
    _wizard_external_tools()
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
