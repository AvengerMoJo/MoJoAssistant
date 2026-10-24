#!/usr/bin/env python3
"""Rotate one credential in the credential engine without the new key passing through any chat or log.

  venv/bin/python scripts/credential_engine_rotate.py cred_xxxx                # prompts (hidden) for the new key
  NEW_KEY=... venv/bin/python scripts/credential_engine_rotate.py cred_xxxx --from-env NEW_KEY
  ... --no-verify     rotate without trying the key at the provider first (explicit opt-out)

The service tries the new key against every endpoint that uses the credential and refuses it (old key kept)
if the provider does not accept it. The key is never printed; only the outcome is.
"""
import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

SIB = Path.home() / "Development" / "Personal"
sys.path[:0] = [str(SIB / "ai-credential-manager"), str(SIB / "ai-resource-manager")]
from credential_manager.owner_client import ServiceClient  # noqa: E402

OWNER_CLIENT = Path.home() / ".config" / "ai-credential-manager" / "owner_admin_client.json"


async def main(cred: str, value: str, verify: bool) -> int:
    client = ServiceClient.from_file(OWNER_CLIENT)
    tenant = json.loads(OWNER_CLIENT.read_text())["tenant_id"]
    out = await client.call("rotate_credential", f"admin:vault:manage:{tenant}", credential_id=cred,
                            new_value=value.strip(), verify=verify)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("credential_id")
    ap.add_argument("--from-env", metavar="VAR")
    ap.add_argument("--no-verify", action="store_true")
    a = ap.parse_args()
    v = os.environ.get(a.from_env, "") if a.from_env else getpass.getpass("new key (hidden): ")
    if not v.strip():
        raise SystemExit("no key supplied")
    sys.exit(asyncio.run(main(a.credential_id, v, not a.no_verify)))
