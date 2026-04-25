#!/usr/bin/env python3
"""
resource_config.py — Resource pool setup and management for MoJoAssistant

The ONBOARDING tool. Detects available LLM backends and manages permanent
entries in ~/.memory/config/resource_pool.json (the personal override layer).

Runtime auto-discovery (dynamic_discovery: true) handles models that come
and go while the server is running. This tool handles EXPLICIT configuration:
resources you want registered regardless of what's currently loaded in LMStudio.

Usage:
    python scripts/resource_config.py detect               # scan running backends
    python scripts/resource_config.py show                 # current pool
    python scripts/resource_config.py add <brain_id>       # add detected backend
    python scripts/resource_config.py add-cloud gemini --api-key AIza...
    python scripts/resource_config.py add-cloud openrouter --api-key sk-or-v1-...
    python scripts/resource_config.py remove <resource_id> # disable a resource
    python scripts/resource_config.py detect --suggest     # preview entries only
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

PERSONAL_POOL_PATH = Path.home() / ".memory" / "config" / "resource_pool.json"

_CLOUD_TEMPLATES = {
    "gemini": {
        "type": "api",
        "provider": "google",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "tier": "free_api",
        "priority": 60,
        "enabled": True,
        "context_limit": 1000000,
        "output_limit": 65536,
        "description": "Gemini 2.5 Flash",
    },
    "openrouter": {
        "type": "api",
        "provider": "openai-compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openrouter/auto",
        "tier": "free_api",
        "priority": 10,
        "enabled": True,
        "context_limit": 131072,
        "output_limit": 8192,
        "description": "OpenRouter free-tier routing",
    },
    "anthropic": {
        "type": "api",
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-6",
        "tier": "paid",
        "priority": 50,
        "enabled": True,
        "context_limit": 200000,
        "output_limit": 16000,
        "description": "Anthropic Claude (paid)",
    },
}


def _load_personal_pool() -> Dict[str, Any]:
    if PERSONAL_POOL_PATH.exists():
        return json.loads(PERSONAL_POOL_PATH.read_text())
    return {"resources": {}}


def _save_personal_pool(data: Dict[str, Any]) -> None:
    PERSONAL_POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    PERSONAL_POOL_PATH.write_text(json.dumps(data, indent=2))


def cmd_detect(args) -> None:
    """Scan for running LLM backends and show what was found."""
    from tools.brain_detector import discover_brains, validate_brain
    brains = discover_brains()
    available = [b for b in brains if b.available]
    unavailable = [b for b in brains if not b.available]

    if not brains:
        print("No backends detected. Is LMStudio / Ollama running?")
        return

    print(f"Detected {len(available)} available, {len(unavailable)} unreachable:\n")
    for b in available:
        v = validate_brain(b)
        rid, entry = b.to_resource_entry()
        print(f"  ✓  {b.backend}  {b.name}")
        print(f"       url={b.base_url}  ctx={b.context_limit}  resource_id={rid}")
        if v["warnings"]:
            for w in v["warnings"]:
                print(f"       ⚠ {w}")
        if args.suggest:
            print(f"       → add with: resource_config.py add {rid}")
        print()

    if unavailable:
        print("Unreachable:")
        for b in unavailable:
            print(f"  ✗  {b.backend}  {b.base_url or ''}  ({b.error})")


def cmd_show(args) -> None:
    """Show the current personal resource pool."""
    pool = _load_personal_pool()
    resources = pool.get("resources", {})
    if not resources:
        print("Personal pool is empty. Run 'detect' then 'add' to populate it.")
        return

    print(f"Personal resource pool  ({PERSONAL_POOL_PATH})\n")
    for rid, entry in resources.items():
        enabled = "✓" if entry.get("enabled", True) else "✗"
        tier = entry.get("tier", "?")
        priority = entry.get("priority", "?")
        model = entry.get("model") or "(dynamic)"
        print(f"  {enabled}  [{priority:>3}]  {rid:35s}  {tier:10s}  {model}")


def cmd_add(args) -> None:
    """Add a detected local backend to the permanent pool."""
    from tools.brain_detector import discover_brains
    brains = discover_brains()
    available = [b for b in brains if b.available]

    # Match by resource_id prefix or brain id
    matched = None
    for b in available:
        rid, _ = b.to_resource_entry()
        if args.brain_id in (rid, b.id, b.name):
            matched = b
            break
        # Fuzzy: resource_id starts with the given name
        if rid.startswith(args.brain_id) or args.brain_id in b.id:
            matched = b
            break

    if not matched:
        ids = [b.to_resource_entry()[0] for b in available]
        print(f"No available backend matching '{args.brain_id}'.")
        print(f"Available: {ids}")
        print("Run 'detect' to see what's running.")
        sys.exit(1)

    rid, entry = matched.to_resource_entry(
        resource_id=args.resource_id or None,
        priority=args.priority,
    )

    pool = _load_personal_pool()
    pool.setdefault("resources", {})[rid] = entry

    if args.dry_run:
        print(f"Would write to {PERSONAL_POOL_PATH}:\n")
        print(json.dumps({rid: entry}, indent=2))
    else:
        _save_personal_pool(pool)
        print(f"Added '{rid}' to {PERSONAL_POOL_PATH}")
        print(json.dumps(entry, indent=2))


def cmd_add_cloud(args) -> None:
    """Add a cloud provider to the permanent pool."""
    provider = args.provider.lower()
    if provider not in _CLOUD_TEMPLATES:
        print(f"Unknown provider '{provider}'. Known: {list(_CLOUD_TEMPLATES)}")
        sys.exit(1)

    entry = dict(_CLOUD_TEMPLATES[provider])
    if args.api_key:
        entry["api_key"] = args.api_key
    if args.model:
        entry["model"] = args.model
    if args.priority is not None:
        entry["priority"] = args.priority

    if not entry.get("api_key"):
        print(f"Warning: no --api-key provided. Set it manually in {PERSONAL_POOL_PATH}")

    slug = args.resource_id or f"{provider}_{args.account or 'default'}"
    pool = _load_personal_pool()
    pool.setdefault("resources", {})[slug] = entry

    if args.dry_run:
        print(f"Would write to {PERSONAL_POOL_PATH}:\n")
        print(json.dumps({slug: entry}, indent=2))
    else:
        _save_personal_pool(pool)
        print(f"Added '{slug}' to {PERSONAL_POOL_PATH}")
        print(json.dumps(entry, indent=2))


def cmd_remove(args) -> None:
    """Disable a resource (sets enabled: false) or delete it entirely."""
    pool = _load_personal_pool()
    resources = pool.get("resources", {})

    if args.resource_id not in resources:
        print(f"Resource '{args.resource_id}' not in personal pool.")
        sys.exit(1)

    if args.delete:
        del resources[args.resource_id]
        print(f"Deleted '{args.resource_id}'.")
    else:
        resources[args.resource_id]["enabled"] = False
        print(f"Disabled '{args.resource_id}' (use --delete to remove entirely).")

    _save_personal_pool(pool)


def main():
    parser = argparse.ArgumentParser(
        description="MoJoAssistant resource pool configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # detect
    p_detect = sub.add_parser("detect", help="Scan for running LLM backends")
    p_detect.add_argument("--suggest", action="store_true",
                          help="Show resource_config add commands for each found backend")
    p_detect.set_defaults(func=cmd_detect)

    # show
    p_show = sub.add_parser("show", help="Show current personal resource pool")
    p_show.set_defaults(func=cmd_show)

    # add
    p_add = sub.add_parser("add", help="Add a detected local backend to the pool")
    p_add.add_argument("brain_id", help="Backend/model id from 'detect' output")
    p_add.add_argument("--resource-id", help="Override the generated resource_id")
    p_add.add_argument("--priority", type=int, help="Override priority (lower = preferred)")
    p_add.add_argument("--dry-run", action="store_true", help="Print entry without writing")
    p_add.set_defaults(func=cmd_add)

    # add-cloud
    p_cloud = sub.add_parser("add-cloud", help="Add a cloud provider (gemini, openrouter, anthropic)")
    p_cloud.add_argument("provider", choices=list(_CLOUD_TEMPLATES))
    p_cloud.add_argument("--api-key", help="API key (inline; omit to set via env var manually)")
    p_cloud.add_argument("--model", help="Override default model")
    p_cloud.add_argument("--account", help="Account label for the resource_id (e.g. 'work')")
    p_cloud.add_argument("--resource-id", help="Full resource_id override")
    p_cloud.add_argument("--priority", type=int)
    p_cloud.add_argument("--dry-run", action="store_true")
    p_cloud.set_defaults(func=cmd_add_cloud)

    # remove
    p_rm = sub.add_parser("remove", help="Disable or delete a resource")
    p_rm.add_argument("resource_id")
    p_rm.add_argument("--delete", action="store_true", help="Remove entirely (default: just disable)")
    p_rm.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
