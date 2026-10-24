#!/usr/bin/env python3
"""Move ONE resource's key into the credential engine, prove it, and (separately) switch MoJoAssistant over.

  venv/bin/python scripts/credential_engine_migrate.py glm_5_2               # plan only, changes nothing
  venv/bin/python scripts/credential_engine_migrate.py glm_5_2 --apply       # vault + catalog + client grant/policy, then verify
  venv/bin/python scripts/credential_engine_migrate.py glm_5_2 --apply --switch   # ... and flip credential_engine on in resource_pool.json
  venv/bin/python scripts/credential_engine_migrate.py openrouter_free:tinyi       # one ACCOUNT of a provider_accounts group: its key
                                                                                    # is stored once, every resource generated for it
                                                                                    # follows (--switch marks the account credential_engine)

--apply is additive: it COPIES the key into the vault. The old environment variable is not touched, so
nothing MoJoAssistant does today changes. It then proves the engine path: the key MoJo's own client gets
back from the engine must hash to the same value as the key in use now (compared by SHA-256, never printed).
--switch is the cutover for that resource: `credential_engine: true` is written into the runtime
resource_pool.json (backup first, read back and re-parsed). Undo = remove that line.
Removing the old key from .env / resource_pool.env is deliberately NOT done here.

Idempotent: the vault ids it creates are remembered in ~/.memory/state/credential_engine_migration.json,
so a key shared by several resources (one environment variable) is stored once.
"""
import argparse
import asyncio
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIB = Path.home() / "Development" / "Personal"
sys.path[:0] = [str(ROOT), str(SIB / "ai-credential-manager"), str(SIB / "ai-resource-manager")]

from app.config.config_loader import load_layered_json_config  # noqa: E402
from app.config.paths import get_memory_subpath  # noqa: E402
from credential_manager.owner_client import ServiceClient  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from credential_engine_import import OWNER_CLIENT, build_payload  # noqa: E402

BOOTSTRAP = Path.home() / ".memory" / "config" / "ai_credential_manager_client.json"
RUNTIME_POOL = Path(get_memory_subpath("config", "resource_pool.json"))
STATE = Path(get_memory_subpath("state", "credential_engine_migration.json"))


def sha(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()[:12]


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"providers": {}, "credentials": {}}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2))


def load_service_env() -> None:
    """The service gets its keys from .env (systemd EnvironmentFile); a shell does not. Read the same file so the
    pool built here sees the same keys the running service does. Existing environment wins, as with systemd."""
    import os
    env = ROOT / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.removeprefix("export ").partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def current_key(rid: str):
    """The key MoJoAssistant uses for this resource today, plus the env var name it comes from."""
    from app.scheduler.resource_pool import ResourceManager
    r = ResourceManager()._resources.get(rid)
    if r is None:
        raise SystemExit(f"{rid!r} is not in the resource pool")
    if r.credential_engine:
        raise SystemExit(f"{rid} already reads its key from the engine")
    if not r.api_key or not r.api_key_env:
        raise SystemExit(f"{rid} has no key from a named environment variable; nothing to migrate")
    return r, r.api_key, r.api_key_env


async def main_account(spec: str, apply: bool, switch: bool) -> int:
    """group:account -- one account of provider_accounts.<group>. One key, N generated resources."""
    group, _, acct = spec.partition(":")
    load_service_env()
    resources, pools, _ = build_payload()
    runtime = json.loads(RUNTIME_POOL.read_text())
    acfg = (((runtime.get("provider_accounts") or {}).get(group) or {}).get("accounts") or {}).get(acct)
    if not acfg:
        raise SystemExit(f"provider_accounts.{group}.accounts.{acct} is not in the runtime resource_pool.json")
    if acfg.get("credential_engine"):
        raise SystemExit(f"{group}:{acct} already reads its key from the engine")
    var = acfg.get("key_var") or acfg.get("api_key_env")
    ids = sorted(r for r in resources if r.startswith(f"{group}_{acct}_"))
    if not ids:
        raise SystemExit(f"no resources are generated for {group}:{acct}")
    # the key as the pool resolves it today (environment, then ~/.memory/resource_pool.env)
    from app.scheduler.resource_pool import ResourceManager
    live = ResourceManager()._resources.get(ids[0])
    key = (live.api_key if live else None) or ""
    if not key:
        raise SystemExit(f"the pool resolves no key for ${var}; nothing to migrate")
    base_url = resources[ids[0]]["base_url"]
    owner = ServiceClient.from_file(OWNER_CLIENT)
    tenant = json.loads(OWNER_CLIENT.read_text())["tenant_id"]
    admin = f"admin:vault:manage:{tenant}"
    st = load_state()
    already_cred = st["credentials"].get(var)
    print(f"account    {group}:{acct}  ->  {len(ids)} resources ({ids[0]} ...)")
    print(f"key        from ${var}  (sha256 {sha(key)}…, length {len(key)})")
    print(f"vault      {'credential ' + already_cred + ' already holds this key' if already_cred else 'a new credential will be stored (encrypted)'}")
    print(f"engine     all {len(ids)} catalog entries get credential_ref (tier {resources[ids[0]].get('tier')}, covered by MoJo's policy)")
    print(f"MoJo       {'provider_accounts.' + group + '.accounts.' + acct + '.credential_engine=true will be written' if switch else 'unchanged (no --switch)'}")
    if not apply:
        print("\nDRY RUN - nothing changed. Re-run with --apply.")
        return 0
    pid = st["providers"].get(base_url)
    if not pid:
        pid = (await owner.call("register_provider", admin, display_name=group, base_url=base_url,
                                auth_style="bearer_header"))["provider_id"]
        st["providers"][base_url] = pid
        save_state(st)
    cid = already_cred
    if not cid:
        cid = (await owner.call("register_credential", admin, provider_id=pid, value=key,
                                description=f"${var} ({group}:{acct}, migrated from MoJoAssistant)"))["credential_id"]
        st["credentials"][var] = cid
        save_state(st)
    out = await owner.call("import_resources", admin, resources={r: dict(resources[r], credential_ref=cid) for r in ids},
                           quota_pools=pools, dry_run=False)
    if out["rejected"]:
        raise SystemExit(f"engine rejected definitions: {out['rejected']}")
    mojo = json.loads(BOOTSTRAP.read_text())["mojoassistant_client"]["client_id"]
    need = f"tenant:{tenant}:acquire"
    if not any(g["resource_scope"] == need and not g["revoked"] for g in await owner.call("list_grants", admin, client_id=mojo)):
        await owner.call("grant_access", admin, client_id=mojo, resource_scope=need)
    from app.scheduler.credential_engine_client import CredentialEngineClient
    probe_id = next(r for r in ids if resources[r].get("enabled", True))
    got = CredentialEngineClient().api_key(probe_id)
    if got is None or sha(got) != sha(key):
        raise SystemExit(f"VERIFY FAILED: the engine handed MoJo a different key for {probe_id} ({sha(got or '')} != {sha(key)})")
    print(f"\nverified   engine hands MoJo's client the same key for {probe_id} (sha256 {sha(got)}…)")
    if switch:
        data = json.loads(RUNTIME_POOL.read_text())
        shutil.copy2(RUNTIME_POOL, RUNTIME_POOL.with_name(RUNTIME_POOL.name + f".bak_engine_{group}_{acct}"))
        data["provider_accounts"][group]["accounts"][acct]["credential_engine"] = True
        RUNTIME_POOL.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        assert json.loads(RUNTIME_POOL.read_text())["provider_accounts"][group]["accounts"][acct]["credential_engine"] is True
        print(f"switched   {group}:{acct}: credential_engine=true written (backup .bak_engine_{group}_{acct})")
    return 0


async def main(rid: str, apply: bool, switch: bool) -> int:
    if ":" in rid:
        return await main_account(rid, apply, switch)
    load_service_env()
    resources, pools, _ = build_payload()
    if rid not in resources:
        raise SystemExit(f"{rid!r} is not in resource_pool.json's flat resources/provider accounts")
    res, key, var = current_key(rid)
    owner = ServiceClient.from_file(OWNER_CLIENT)
    tenant = json.loads(OWNER_CLIENT.read_text())["tenant_id"]
    admin = f"admin:vault:manage:{tenant}"
    mojo = json.loads(BOOTSTRAP.read_text())["mojoassistant_client"]["client_id"]
    st = load_state()
    already_cred = st["credentials"].get(var)

    print(f"resource   {rid}  ({res.provider}, {res.model}, tier {res.tier.value}, priority {res.priority})")
    print(f"key        from ${var}  (sha256 {sha(key)}…, length {len(key)})")
    print(f"vault      {'credential ' + already_cred + ' already holds this key' if already_cred else 'a new credential will be stored (encrypted)'}")
    print(f"engine     catalog entry gets credential_ref; MoJo client gets tenant:{tenant}:acquire and a policy covering this resource")
    print(f"MoJo       {'credential_engine:true will be written to resource_pool.json' if switch else 'unchanged (no --switch)'}")
    if not apply:
        print("\nDRY RUN - nothing changed. Re-run with --apply.")
        return 0

    # 1. provider + credential (reused when this key / endpoint was already stored)
    pid = st["providers"].get(res.base_url)
    if not pid:
        pid = (await owner.call("register_provider", admin, display_name=res.provider, base_url=res.base_url,
                                auth_style="bearer_header"))["provider_id"]
        st["providers"][res.base_url] = pid
        save_state(st)
    cid = already_cred
    if not cid:
        cid = (await owner.call("register_credential", admin, provider_id=pid, value=key,
                                description=f"${var} (migrated from MoJoAssistant)"))["credential_id"]
        st["credentials"][var] = cid
        save_state(st)

    # 2. catalog entry now references the credential
    definition = dict(resources[rid], credential_ref=cid)
    out = await owner.call("import_resources", admin, resources={rid: definition}, dry_run=False)
    if out["rejected"]:
        raise SystemExit(f"engine rejected the definition: {out['rejected']}")

    # 3. MoJo's client may be handed keys, within a policy that names what it is allowed to take
    grants = await owner.call("list_grants", admin, client_id=mojo)
    need = f"tenant:{tenant}:acquire"
    if not any(g["resource_scope"] == need and not g["revoked"] for g in grants):
        await owner.call("grant_access", admin, client_id=mojo, resource_scope=need)
    pol = (await owner.call("get_client_policy", admin, client_id=mojo))["policy"]
    tiers = sorted(set(pol["allowed_tiers"]) | {res.tier.value})
    paid = sorted(set(pol.get("paid_approved") or []) | ({rid} if res.tier.value == "paid" else set()))
    await owner.call("set_client_policy", admin, client_id=mojo, policy={
        "allowed_tiers": tiers, "max_data_scope": "third_party", "resource_ids": None, "paid_approved": paid,
        "max_leases_per_hour": pol["max_leases_per_hour"], "lease_ttl_s": pol["lease_ttl_s"]})

    # 4. prove it with MoJo's own client path
    boot = json.loads(BOOTSTRAP.read_text())
    if "tenant_id" not in boot:
        boot["tenant_id"] = tenant
        BOOTSTRAP.write_text(json.dumps(boot, indent=2))
    from app.scheduler.credential_engine_client import CredentialEngineClient
    got = CredentialEngineClient().api_key(rid)
    if got is None or sha(got) != sha(key):
        raise SystemExit(f"VERIFY FAILED: the engine handed MoJo a different key for {rid} ({sha(got or '')} != {sha(key)})")
    print(f"\nverified   engine hands MoJo's client the same key for {rid} (sha256 {sha(got)}…)")
    health = await owner.call("probe_resources", admin, resource_id=rid)
    print(f"probe      {health['health'].get(rid, {}).get('state', 'not probed (health_check off for this resource)')}"
          f"  {health['health'].get(rid, {}).get('detail', '')}")

    # 5. cutover for this resource only
    if switch:
        raw = RUNTIME_POOL.read_text()
        data = json.loads(raw)
        if rid not in data.get("resources", {}):
            raise SystemExit(f"{rid} is not a flat resource in the runtime resource_pool.json; switch it by hand")
        shutil.copy2(RUNTIME_POOL, RUNTIME_POOL.with_name(RUNTIME_POOL.name + ".bak_engine_" + rid))
        data["resources"][rid]["credential_engine"] = True
        RUNTIME_POOL.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        back = json.loads(RUNTIME_POOL.read_text())["resources"][rid]
        assert back.get("credential_engine") is True, "read-back failed"
        print(f"switched   {rid}: credential_engine=true written to {RUNTIME_POOL.name} (backup .bak_engine_{rid})")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("resource_id")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--switch", action="store_true", help="after verifying, make MoJoAssistant read this resource's key from the engine")
    a = ap.parse_args()
    if a.switch and not a.apply:
        raise SystemExit("--switch needs --apply")
    sys.exit(asyncio.run(main(a.resource_id, a.apply, a.switch)))
