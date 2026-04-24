"""
First-run helpers for MoJoAssistant.

Provides:
- unpack_bundled_roles()  — copy config/roles/*.json to ~/.memory/roles/ if absent
- OWNER_PROFILE_TEMPLATE  — default owner profile schema
- create_owner_profile()  — write ~/.memory/owner_profile.json if absent
- load_owner_profile()    — read ~/.memory/owner_profile.json (empty dict if missing)
- detect_llm_backends()   — probe common local LLM server ports
- BACKEND_CATALOG         — known backends with model recommendations
"""

import json
import shutil
import socket
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Bundled roles
# ---------------------------------------------------------------------------

# Project root is two levels up from this file (app/config/first_run.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_BUNDLED_ROLES_DIR = _PROJECT_ROOT / "config" / "roles"


def unpack_bundled_roles(memory_path: Path) -> list[str]:
    """Copy any config/roles/*.json that doesn't exist yet in memory_path/roles/.

    Skips files whose name ends with '.example'.
    Never overwrites existing user-customised roles.

    Returns:
        List of role ids that were freshly unpacked.
    """
    roles_dir = memory_path / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)

    unpacked: list[str] = []

    for src in sorted(_BUNDLED_ROLES_DIR.glob("*.json")):
        if src.name.endswith(".example"):
            continue

        dest = roles_dir / src.name
        if dest.exists():
            continue  # idempotent — never overwrite

        shutil.copy2(src, dest)
        # Derive role id from filename (strip .json)
        role_id = src.stem
        unpacked.append(role_id)

    return unpacked


# ---------------------------------------------------------------------------
# Owner profile
# ---------------------------------------------------------------------------

OWNER_PROFILE_TEMPLATE: dict = {
    "owner_id": "",
    "name": "",
    "preferred_name": "",
    "pronouns": "",
    "timezone": "Asia/Taipei",
    "languages": ["en"],
    "identity": {
        "summary": "",
        "location_context": "",
        "roles_in_life": [],
    },
    "communication_preferences": {
        "style": ["direct", "high-signal", "low-fluff"],
        "verbosity_default": "concise",
        "likes_pushback_when_reasoned": True,
        "prefers_specific_recommendations": True,
    },
    "workflow_preferences": {
        "authorized_command_channel": "mcp",
        "dashboard_chat_is_read_only": True,
        "prefers_private_debrief_in_dashboard": True,
        "wants_clear_mode_labels": True,
    },
    "privacy_preferences": {
        "prefer_local_when_possible": True,
        "wants_auditability_for_external_use": True,
        "sensitive_domains": [
            "personal memory",
            "spiritual notes",
            "security infrastructure",
        ],
    },
    "core_goals": [],
    "assistant_relationships": {
        "researcher": {
            "relationship": "research partner",
            "focus": ["deep analysis", "comparative reasoning", "explanation"],
        },
        "analyst": {
            "relationship": "security and operations specialist",
            "focus": ["hardening", "infrastructure", "risk surfacing"],
        },
        "coder": {
            "relationship": "code reviewer",
            "focus": ["code quality", "security", "maintainability"],
        },
    },
    "policy_authority": {
        "is_memory_owner": True,
        "can_approve_sensitive_actions": True,
        "can_override_role_defaults": True,
    },
}


def create_owner_profile(
    memory_path: Path, overrides: Optional[dict] = None
) -> Path:
    """Write ~/.memory/owner_profile.json if it doesn't exist.

    Merges *overrides* (top-level keys only) into the template before writing.
    Never overwrites an existing file.

    Returns:
        Path to the owner_profile.json file.
    """
    profile_path = memory_path / "owner_profile.json"

    if profile_path.exists():
        return profile_path

    profile = dict(OWNER_PROFILE_TEMPLATE)
    if overrides:
        profile.update(overrides)

    memory_path.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n")

    return profile_path


# ---------------------------------------------------------------------------
# LLM backend detection
# ---------------------------------------------------------------------------

# Each entry: (backend_id, label, host, port, base_url_path, env_var)
# model_ladder: list of (model_id, label, min_vram_gb, pull_cmd)
BACKEND_CATALOG: list[dict] = [
    {
        "id": "ollama",
        "label": "Ollama",
        "host": "localhost",
        "port": 11434,
        "base_url": "http://localhost:11434/v1",
        "env_var": "LMSTUDIO_BASE_URL",   # reuse OpenAI-compat var
        "install_url": "https://ollama.com",
        "model_ladder": [
            {"model": "qwen3:1.7b",  "label": "Qwen3-1.7B  (~1 GB) — CPU-only, minimal",          "min_vram_gb": 0,  "pull_cmd": "ollama pull qwen3:1.7b"},
            {"model": "qwen3:4b",    "label": "Qwen3-4B    (~2.5 GB) — 4–8 GB VRAM, recommended", "min_vram_gb": 4,  "pull_cmd": "ollama pull qwen3:4b"},
            {"model": "qwen3:8b",    "label": "Qwen3-8B    (~5 GB)   — 8 GB VRAM",                "min_vram_gb": 8,  "pull_cmd": "ollama pull qwen3:8b"},
            {"model": "qwen3:14b",   "label": "Qwen3-14B   (~9 GB)   — 16 GB VRAM",               "min_vram_gb": 16, "pull_cmd": "ollama pull qwen3:14b"},
            {"model": "qwen3:30b-a3b","label": "Qwen3-30B-A3B (~18 GB) — 24 GB VRAM",            "min_vram_gb": 24, "pull_cmd": "ollama pull qwen3:30b-a3b"},
        ],
        "default_model": "qwen3:4b",
    },
    {
        "id": "lmstudio",
        "label": "LM Studio",
        "host": "localhost",
        "port": 1234,
        "base_url": "http://localhost:1234/v1",
        "env_var": "LMSTUDIO_BASE_URL",
        "install_url": "https://lmstudio.ai",
        "model_ladder": [
            {"model": "qwen3-1.7b",    "label": "Qwen3-1.7B  (~1 GB) — CPU-only, minimal",          "min_vram_gb": 0},
            {"model": "qwen3-4b",      "label": "Qwen3-4B    (~2.5 GB) — 4–8 GB VRAM, recommended", "min_vram_gb": 4},
            {"model": "qwen3-8b",      "label": "Qwen3-8B    (~5 GB)   — 8 GB VRAM",                "min_vram_gb": 8},
            {"model": "qwen3-14b",     "label": "Qwen3-14B   (~9 GB)   — 16 GB VRAM",               "min_vram_gb": 16},
            {"model": "qwen3-30b-a3b", "label": "Qwen3-30B-A3B (~18 GB) — 24 GB VRAM",             "min_vram_gb": 24},
        ],
        "default_model": "qwen3-4b",
    },
    {
        "id": "llamaserver",
        "label": "llama-server (llama.cpp)",
        "host": "localhost",
        "port": 8080,
        "base_url": "http://localhost:8080/v1",
        "env_var": "LMSTUDIO_BASE_URL",
        "install_url": "https://github.com/ggml-org/llama.cpp",
        "model_ladder": [
            {"model": "qwen3-1.7b-q4.gguf", "label": "Qwen3-1.7B Q4 (~1 GB) — CPU-only, minimal",          "min_vram_gb": 0},
            {"model": "qwen3-4b-q4.gguf",   "label": "Qwen3-4B Q4 (~2.5 GB) — 4–8 GB VRAM, recommended", "min_vram_gb": 4},
            {"model": "qwen3-8b-q4.gguf",   "label": "Qwen3-8B Q4 (~5 GB)   — 8 GB VRAM",                "min_vram_gb": 8},
        ],
        "default_model": "qwen3-4b-q4.gguf",
    },
    {
        "id": "vllm",
        "label": "vLLM",
        "host": "localhost",
        "port": 8000,
        "base_url": "http://localhost:8000/v1",
        "env_var": "LMSTUDIO_BASE_URL",
        "install_url": "https://docs.vllm.ai",
        "model_ladder": [
            {"model": "Qwen/Qwen3-8B",      "label": "Qwen3-8B    (~5 GB)   — 8 GB VRAM",  "min_vram_gb": 8},
            {"model": "Qwen/Qwen3-14B",     "label": "Qwen3-14B   (~9 GB)   — 16 GB VRAM", "min_vram_gb": 16},
            {"model": "Qwen/Qwen3-30B-A3B", "label": "Qwen3-30B-A3B (~18 GB) — 24 GB VRAM","min_vram_gb": 24},
            {"model": "Qwen/Qwen3-72B",     "label": "Qwen3-72B   (Q4, ~40 GB) — 48 GB+",  "min_vram_gb": 48},
        ],
        "default_model": "Qwen/Qwen3-8B",
    },
]


def detect_llm_backends(timeout: float = 0.5) -> list[dict]:
    """Probe known LLM backend ports. Returns list of detected backend dicts."""
    detected = []
    for backend in BACKEND_CATALOG:
        try:
            with socket.create_connection((backend["host"], backend["port"]), timeout=timeout):
                detected.append(backend)
        except OSError:
            pass
    return detected


def recommend_model(backend: dict, vram_gb: int) -> dict:
    """Return the highest-tier model in the ladder that fits within vram_gb.
    Falls back to the smallest (index 0) if nothing fits."""
    ladder = backend["model_ladder"]
    best = ladder[0]
    for entry in ladder:
        if entry["min_vram_gb"] <= vram_gb:
            best = entry
    return best


# ---------------------------------------------------------------------------

def load_owner_profile(memory_path: Path) -> dict:
    """Load owner_profile.json.

    Returns:
        Parsed dict, or empty dict if the file does not exist.
    """
    profile_path = memory_path / "owner_profile.json"
    if not profile_path.exists():
        return {}

    try:
        return json.loads(profile_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Demo task seeding
# ---------------------------------------------------------------------------

_DEMO_TASKS = [
    {
        "id": "demo_rebecca_summarise",
        "type": "internal_assignment",
        "description": "Researcher: summarise recent memory and what you know about this project",
        "config": {
            "role_id": "researcher",
            "prompt": (
                "Summarise what you know about MoJoAssistant from memory and knowledge. "
                "Cover: what the system does, the main roles available, and any recent activity "
                "you can find. Keep it concise — this is a first-run orientation summary."
            ),
            "source": "first_run",
        },
    },
    {
        "id": "demo_ahman_health",
        "type": "internal_assignment",
        "description": "Analyst: check system health (memory path, config files, scheduler storage)",
        "config": {
            "role_id": "analyst",
            "prompt": (
                "Run a quick system health check on MoJoAssistant. Verify: "
                "1) memory path exists and is writable, "
                "2) config files (llm_config.json, resource_pool.json) are present, "
                "3) scheduler storage directory is accessible. "
                "Report findings in a short bullet list."
            ),
            "source": "first_run",
        },
    },
    {
        "id": "demo_carl_review",
        "type": "internal_assignment",
        "description": "Coder: review the first_run.py module for quality issues",
        "config": {
            "role_id": "coder",
            "prompt": (
                "Review app/config/first_run.py. "
                "Flag any 🔴 blockers (correctness, security), 🟡 suggestions (robustness, edge cases), "
                "and 💬 nits (style). Keep the review focused and concise."
            ),
            "source": "first_run",
        },
    },
]


def seed_demo_tasks(storage_path: Path) -> list[str]:
    """Write demo task JSON files into storage_path/tasks/ if they don't exist yet.

    Does NOT start the scheduler — tasks are written as PENDING JSON files so
    the scheduler picks them up on its next wake cycle.

    Returns:
        List of task ids that were seeded.
    """
    from datetime import datetime

    tasks_dir = storage_path / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    seeded: list[str] = []
    for spec in _DEMO_TASKS:
        task_file = tasks_dir / f"{spec['id']}.json"
        if task_file.exists():
            continue

        task_data = {
            "id": spec["id"],
            "type": spec["type"],
            "status": "pending",
            "priority": "medium",
            "description": spec["description"],
            "config": spec["config"],
            "created_at": datetime.now().isoformat(),
            "created_by": "first_run",
            "retry_count": 0,
            "max_retries": 1,
            "dispatch_depth": 0,
        }
        task_file.write_text(json.dumps(task_data, indent=2, ensure_ascii=False) + "\n")
        seeded.append(spec["id"])

    return seeded
