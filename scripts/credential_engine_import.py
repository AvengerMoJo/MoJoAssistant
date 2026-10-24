#!/usr/bin/env python3
"""Load MoJoAssistant's resource table into the credential engine's catalog (definitions only, never keys).

  venv/bin/python scripts/credential_engine_import.py              # dry run: show the diff, change nothing
  venv/bin/python scripts/credential_engine_import.py --apply      # load the clean definitions

Reads the same layered resource_pool.json the live pool reads, expands provider accounts, drops every secret
field (key_var / api_key_env / api_key never leave this machine through this script), and calls the service's
import_resources as the owner-admin client (bootstrapped with `python -m credential_manager.admin
bootstrap-owner`). A resource that needs a key stays OFF in the service until a credential is attached to it,
so loading the definitions does not move any key and does not change how MoJoAssistant routes.

The key each resource uses today is reported by environment variable NAME only, so the next step
(attach credentials one resource at a time) knows what to move.
"""
import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIBLINGS = Path.home() / "Development" / "Personal"
sys.path[:0] = [str(ROOT), str(SIBLINGS / "ai-credential-manager"), str(SIBLINGS / "ai-resource-manager")]

from app.config.config_loader import load_layered_json_config  # noqa: E402
from credential_manager.owner_client import ServiceClient  # noqa: E402
from resource_manager.expansion import expand_provider_accounts  # noqa: E402

OWNER_CLIENT = Path.home() / ".config" / "ai-credential-manager" / "owner_admin_client.json"
SECRET_FIELDS = ("api_key", "key", "secret", "token", "password")


def build_payload():
    data = load_layered_json_config("config/resource_pool.json")
    resources, pools, errors = expand_provider_accounts(data)
    if errors:
        raise SystemExit("resource_pool.json does not expand cleanly:\n  " + "\n  ".join(errors))
    out, key_vars = {}, defaultdict(list)
    for rid, conf in resources.items():
        if not isinstance(conf, dict):
            continue
        conf = {k: v for k, v in conf.items() if k not in SECRET_FIELDS}  # a literal key never leaves this script
        var = conf.get("key_var") or conf.get("api_key_env")
        if var:
            key_vars[var].append(rid)
        conf.setdefault("type", "local" if conf.get("base_url", "").startswith("http://localhost") else "api")
        conf.setdefault("provider", "openai")
        out[rid] = conf
    return out, pools, key_vars


async def main(apply: bool) -> int:
    resources, pools, key_vars = build_payload()
    client = ServiceClient.from_file(OWNER_CLIENT)
    tenant = json.loads(OWNER_CLIENT.read_text())["tenant_id"]
    scope = f"admin:vault:manage:{tenant}"
    # An import REPLACES a definition, and which credential a resource uses lives only on the service side.
    # Carry each existing credential_ref over, or every migrated resource would lose its key on the next import.
    # `credential_engine` is MoJoAssistant's own opt-in flag; the service does not store it.
    existing = await client.call("list_resources", scope)
    rows = existing.get("resources") if isinstance(existing, dict) else existing
    if not isinstance(rows, list):
        raise SystemExit(f"cannot read the service's current definitions (unexpected list_resources answer): {type(existing).__name__}")
    refs = {r.get("id") or r.get("resource_id"): r.get("credential_ref") for r in rows if isinstance(r, dict)}
    for rid, conf in resources.items():
        conf.pop("credential_engine", None)
        if refs.get(rid) and not conf.get("credential_ref"):
            conf["credential_ref"] = refs[rid]
    result = await client.call("import_resources", scope, resources=resources, quota_pools=pools, dry_run=not apply)

    print(f"{'APPLIED' if apply else 'DRY RUN'}: {len(resources)} definitions read from resource_pool.json")
    print(f"  added     {len(result['added'])}")
    print(f"  changed   {len(result['changed'])}  {result['changed'] or ''}")
    print(f"  unchanged {len(result['unchanged'])}")
    print(f"  rejected  {len(result['rejected'])}")
    for rid, why in result["rejected"].items():
        print(f"    - {rid}: {why}")
    if result["notes"]:
        print(f"  notes: {sum(len(v) for v in result['notes'].values())} legacy key fields dropped on the service side")
    print("\nKeys still to move into the vault (environment variable NAME -> resources that use it):")
    for var, rids in sorted(key_vars.items()):
        print(f"  {var}: {len(rids)} resource(s)")
    return 1 if result["rejected"] else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="load the definitions (default is a dry run)")
    sys.exit(asyncio.run(main(ap.parse_args().apply)))
