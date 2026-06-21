#!/usr/bin/env python3
"""Merge the agent-managed CubeSandbox ingress block into ~/.cloudflared/config.yml.

The user's ~/.cloudflared/config.yml serves two tunnels:
  - church-tunnel (c7a1ca2b-c1ea-407d-8078-bdb65412f693): *.eclipsogate.org apps
  - portainer-tunnel (9e8f4c3e-...): cloud/docker/vault/ws_vault/ssh

The agent must NEVER overwrite the user's file wholesale, because the user
curates the other ingress entries themselves (portainer-tunnel uses the
"Published application" flow and isn't in this file).

Instead, this script:
  1. Reads the user's ~/.cloudflared/config.yml
  2. Reads docs/infra/cloudflared-cubesandbox.yml (the overlay)
  3. Removes any existing ingress entries whose hostname is in the overlay
     (so the overlay stays the source of truth for those hostnames)
  4. Appends the overlay entries just before the catch-all
  5. Writes back to ~/.cloudflared/config.yml (or to --out if given)
  6. Validates with `cloudflared tunnel ingress validate` if cloudflared is on PATH

Run from the repo root:
  python scripts/merge_cloudflared_config.py

Use --dry-run to print the merged YAML to stdout without writing.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_USER_CONFIG = Path.home() / ".cloudflared" / "config.yml"
OVERLAY_PATH = REPO_ROOT / "docs" / "infra" / "cloudflared-cubesandbox.yml"


def load_yaml(path: Path):
    with path.open() as f:
        return yaml.safe_load(f)


def dump_yaml(data, path: Path) -> None:
    text = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    path.write_text(text)


def merge(user_cfg_path: Path, overlay_path: Path, out_path: Path) -> dict:
    user_cfg = load_yaml(user_cfg_path)
    overlay_entries = load_yaml(overlay_path) or []
    if not isinstance(overlay_entries, list):
        raise SystemExit(f"Overlay must be a YAML list of ingress entries; got {type(overlay_entries)}")

    overlay_hostnames = {e["hostname"] for e in overlay_entries}

    existing = user_cfg.get("ingress") or []
    preserved = [r for r in existing if r.get("hostname") not in overlay_hostnames]

    # Find the catch-all rule (no hostname) — keep it last
    catchall = [r for r in preserved if "hostname" not in r]
    non_catchall = [r for r in preserved if "hostname" in r]

    if len(catchall) != 1:
        raise SystemExit(
            f"Expected exactly one catch-all ingress rule in {user_cfg_path}, "
            f"found {len(catchall)}"
        )

    merged = non_catchall + overlay_entries + catchall
    user_cfg["ingress"] = merged

    dump_yaml(user_cfg, out_path)
    return user_cfg


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--user-config", type=Path, default=DEFAULT_USER_CONFIG,
                   help=f"Path to user's cloudflared config (default: {DEFAULT_USER_CONFIG})")
    p.add_argument("--overlay", type=Path, default=OVERLAY_PATH,
                   help=f"Overlay file with CubeSandbox ingress entries (default: {OVERLAY_PATH})")
    p.add_argument("--out", type=Path, default=None,
                   help="Output path (default: overwrite --user-config)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print merged YAML to stdout, don't write")
    p.add_argument("--no-backup", action="store_true",
                   help="Skip the .bak backup before overwriting")
    args = p.parse_args()

    if not args.user_config.exists():
        raise SystemExit(f"User config not found: {args.user_config}")
    if not args.overlay.exists():
        raise SystemExit(f"Overlay not found: {args.overlay}")

    out_path = args.out or args.user_config

    if args.dry_run:
        # Render to a temp path so dump_yaml has somewhere to write
        tmp = Path("/tmp/_cloudflared_merged.yml")
        merge(args.user_config, args.overlay, tmp)
        sys.stdout.write(tmp.read_text())
        tmp.unlink()
        return 0

    if not args.no_backup and out_path == args.user_config:
        backup = out_path.with_name(out_path.name + ".bak")
        shutil.copy2(out_path, backup)
        print(f"[merge] backup saved to {backup}", file=sys.stderr)

    merge(args.user_config, args.overlay, out_path)
    print(f"[merge] wrote {out_path}", file=sys.stderr)

    if shutil.which("cloudflared"):
        rc = subprocess.run(
            ["cloudflared", "tunnel", "--config", str(out_path), "ingress", "validate"],
            capture_output=True, text=True,
        ).returncode
        if rc != 0:
            print(f"[merge] WARNING: cloudflared ingress validate failed (rc={rc})", file=sys.stderr)
            return rc

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
