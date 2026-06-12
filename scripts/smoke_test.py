#!/usr/bin/env python3
"""Compare full vs lean agentic tool schemas for configured resources."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def discover_models(base_url: str = "http://localhost:8080", api_key: str = "") -> list[str]:
    import requests
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    base = base_url.rstrip("/")
    for path in ("/v1/models", "/models"):
        try:
            resp = requests.get(f"{base}{path}", headers=headers, timeout=5)
            if resp.status_code == 200:
                return [m.get("id", "") for m in resp.json().get("data", []) if m.get("id")]
        except Exception:
            pass
    return []


def resolve_resource_id(resource_or_model: str) -> str | None:
    from app.scheduler.resource_pool import ResourceManager
    rm = ResourceManager()
    if resource_or_model in rm._resources:
        return resource_or_model
    for rid, resource in rm._resources.items():
        if resource.model == resource_or_model:
            return rid
    return None


async def main_async(args):
    from app.scheduler.agentic_smoke_test import AgenticSmokeTest

    resource_id = resolve_resource_id(args.model)
    if not resource_id:
        raise SystemExit(f"No configured resource found for '{args.model}'. Use a resource_id from resource_status or a configured model string.")

    tester = AgenticSmokeTest()
    integration_checks = ["memory_search", "bash_exec"] if args.integration else None

    if args.mode == "compare":
        result = await tester.compare_tool_schema_modes(
            resource_id=resource_id,
            profile=args.profile,
            integration_checks=integration_checks,
            repeats=args.repeats,
        )
    else:
        result = (await tester.run(
            resource_id=resource_id,
            profile=args.profile,
            integration_checks=integration_checks,
            tool_schema_mode=args.mode,
            debug_artifact=args.debug_artifact,
        )).to_dict()
    print(json.dumps(result, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="Evaluate full vs lean tool schemas on configured resources")
    parser.add_argument("--list", action="store_true", help="List models visible on the server and exit")
    parser.add_argument("--model", "-m", help="Configured resource_id or configured model string")
    parser.add_argument("--server", default="http://localhost:8080")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--profile", default="fast_gate", choices=["fast_gate", "standard_agentic", "reasoning_stress"])
    parser.add_argument("--mode", default="compare", choices=["compare", "full", "lean"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--integration", action="store_true")
    parser.add_argument("--debug-artifact", action="store_true")
    args = parser.parse_args()

    if args.list:
        print(json.dumps(discover_models(args.server, args.api_key), indent=2))
        return
    if not args.model:
        parser.error("--model is required unless --list is used")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
