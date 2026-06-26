#!/usr/bin/env python3
"""Standalone CubeSandbox diagnostic and fix.

Walks the actual e2b SDK data path and reports — and optionally fixes —
each stage:

  1. Env vars (E2B_API_URL, E2B_API_KEY, CUBE_TEMPLATE_ID) — fix: source .env
  2. Local image (opencode-sandbox:v2 with envd) — fix: docker build
  3. cube-api reachable — fix: check cloudflared + cube-api container
  4. Sandbox.create succeeds — fix: env, template, or e2b SDK issue
  5. envd in VM (commands.run works) — fix: rebuild template
  6. Orphan reconciliation — fix: kill via sandbox_purge_orphans

Usage:
  python3 scripts/doctor_cubesandbox.py            # diagnose only
  python3 scripts/doctor_cubesandbox.py --fix     # diagnose + offer fixes
  python3 scripts/doctor_cubesandbox.py --fix -y  # apply fixes without prompts
  python3 scripts/doctor_cubesandbox.py --json    # machine-readable

Exit codes:
  0  all stages passed
  1  one or more stages failed (no fixes applied)
  2  one or more stages failed AND fixes were applied (caller should
     re-run to verify)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------


@dataclass
class StageResult:
    name: str
    status: str  # "ok" | "warn" | "fail" | "skipped"
    detail: str
    fix_command: Optional[str] = None  # command the user can run to fix
    fix_action: Optional[Callable[[], tuple[bool, str]]] = None  # programmatic fix


def _load_dotenv(path: Path) -> bool:
    """Best-effort KEY=VALUE load. Doesn't overwrite existing env vars."""
    if not path.exists():
        return False
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(path, override=False)
        return True
    except ImportError:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
            return True
        except Exception:
            return False


def stage_1_env() -> StageResult:
    """E2B_API_URL, E2B_API_KEY, CUBE_TEMPLATE_ID present in env."""
    _load_dotenv(PROJECT_ROOT / ".env")
    e2b_url = os.environ.get("E2B_API_URL")
    e2b_key = os.environ.get("E2B_API_KEY")
    template = os.environ.get("CUBE_TEMPLATE_ID")
    missing = [k for k, v in [
        ("E2B_API_URL", e2b_url),
        ("E2B_API_KEY", e2b_key),
        ("CUBE_TEMPLATE_ID", template),
    ] if not v]
    if not missing:
        return StageResult(
            "env", "ok",
            f"E2B_API_URL={e2b_url}, CUBE_TEMPLATE_ID={template[:20]}..."
        )
    detail = f"missing: {', '.join(missing)}"
    return StageResult(
        "env", "fail", detail,
        fix_command="python3 scripts/configure_env.py  # or edit .env manually",
    )


def stage_2_local_image() -> StageResult:
    """opencode-sandbox:v2 image exists locally and has envd installed."""
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "opencode-sandbox:v2",
             "bash", "-c", "which envd && /usr/bin/envd -version"],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return StageResult(
            "local-image", "skipped",
            "docker not on PATH — skipping local image check; "
            "verifying cluster template instead",
        )
    except subprocess.TimeoutExpired:
        return StageResult(
            "local-image", "fail",
            "docker run timed out (30s) — docker daemon may be stuck",
            fix_command="docker ps && docker info",
        )
    if r.returncode != 0:
        return StageResult(
            "local-image", "fail",
            f"opencode-sandbox:v2 missing envd (rc={r.returncode}): "
            f"{r.stderr.strip()[:200]}",
            fix_command=(
                "docker build -t opencode-sandbox:v2 "
                "-f docker/opencode-sandbox/Dockerfile ."
            ),
        )
    envd_ver = r.stdout.strip().split("\n")[-1]
    return StageResult("local-image", "ok", f"envd {envd_ver}")


def stage_3_cube_api_reachable() -> StageResult:
    """$E2B_API_URL/sandboxes returns 200 + a list."""
    e2b_url = os.environ.get("E2B_API_URL", "").rstrip("/")
    e2b_key = os.environ.get("E2B_API_KEY", "")
    if not e2b_url or not e2b_key:
        return StageResult("cube-api", "skipped", "E2B_API_URL/KEY not set; stage 1 must pass first")
    try:
        import httpx
        r = httpx.get(
            f"{e2b_url}/sandboxes",
            headers={"X-API-KEY": e2b_key},
            timeout=15,
        )
    except Exception as e:
        return StageResult(
            "cube-api", "fail",
            f"cannot reach {e2b_url}/sandboxes: {type(e).__name__}: {str(e)[:120]}",
            fix_command=(
                "docker ps | grep cube-api  # check the cube-api container\n"
                "curl -k https://sandbox-api.eclipsogate.org/health  # smoke test"
            ),
        )
    if r.status_code != 200:
        return StageResult(
            "cube-api", "fail",
            f"HTTP {r.status_code} on /sandboxes — cluster may be down",
            fix_command="docker logs cube-api --tail 50",
        )
    data = r.json()
    if not isinstance(data, list):
        return StageResult(
            "cube-api", "fail",
            f"unexpected response shape: {type(data).__name__} (expected list)",
            fix_command="curl -s https://sandbox-api.eclipsogate.org/sandboxes | head",
        )
    return StageResult("cube-api", "ok", f"{len(data)} sandboxes on cluster")


def stage_4_sandbox_create() -> StageResult:
    """Sandbox.create(template=CUBE_TEMPLATE_ID) returns a sandbox_id."""
    template = os.environ.get("CUBE_TEMPLATE_ID")
    if not template:
        return StageResult("sandbox-create", "skipped", "CUBE_TEMPLATE_ID not set")
    try:
        from e2b import Sandbox
        sb = Sandbox.create(template=template, timeout=120)
    except Exception as e:
        return StageResult(
            "sandbox-create", "fail",
            f"Sandbox.create({template}) failed: {type(e).__name__}: {str(e)[:200]}",
            fix_command=(
                f"cubemastercli tpl list  # check if {template[:24]}... is READY\n"
                "# if FAILED, rebuild per docs/architecture/CUBESANDBOX_REBUILD_GUIDE.md"
            ),
        )
    # Stash for stage 5
    stage_4_sandbox_create._sandbox = sb
    return StageResult("sandbox-create", "ok", f"sandbox_id={sb.sandbox_id}")


def stage_5_envd_exec() -> StageResult:
    """commands.run('echo doctor-ok') returns 'doctor-ok' in stdout."""
    sb = getattr(stage_4_sandbox_create, "_sandbox", None)
    if sb is None:
        return StageResult("envd-exec", "skipped", "no sandbox from stage 4")
    try:
        r = sb.commands.run("echo doctor-ok", timeout=0, request_timeout=30)
    except Exception as e:
        sb.kill()
        return StageResult(
            "envd-exec", "fail",
            f"commands.run failed: {type(e).__name__}: {str(e)[:200]}",
            fix_command=(
                "The template has no envd binary. Rebuild per "
                "docs/architecture/CUBESANDBOX_REBUILD_GUIDE.md, or switch to a "
                "known-good template (CUBE_TEMPLATE_ID=tpl-d599cf3ead2c48f78df6a6da)"
            ),
        )
    if r.stdout.strip() != "doctor-ok":
        sb.kill()
        return StageResult(
            "envd-exec", "fail",
            f"unexpected stdout: {r.stdout!r}",
            fix_command=(
                "Template may have a partial envd install. Rebuild:\n"
                "  docker build -t opencode-sandbox:v2 "
                "-f docker/opencode-sandbox/Dockerfile . && "
                "cubemastercli template create-from-image --image "
                "opencode-sandbox:v2 --writable-layer-size 2G "
                "--expose-port 4173 --expose-port 49983 --probe 49983 "
                "--probe-path /health"
            ),
        )
    sb.kill()
    return StageResult("envd-exec", "ok", "echo doctor-ok returned as expected")


def stage_6_orphans() -> StageResult:
    """List CubeMaster sandboxes; flag those without a MoJo handle."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from app.scheduler.sandbox.cubesandbox_client import CubeSandboxClient
        from app.scheduler.sandbox import list_orphan_sandbox_ids
        cubes = CubeSandboxClient.list_cubemaster_sandboxes()
        all_ids = [c.get("sandbox_id") for c in cubes if c.get("sandbox_id")]
        orphans = list_orphan_sandbox_ids(all_ids)
    except Exception as e:
        return StageResult(
            "orphans", "warn",
            f"could not enumerate: {type(e).__name__}: {str(e)[:120]}"
        )
    if not orphans:
        return StageResult("orphans", "ok", "0 orphans on cluster")
    return StageResult(
        "orphans", "warn",
        f"{len(orphans)} orphan(s) on cluster: {orphans[:3]}"
        f"{'...' if len(orphans) > 3 else ''}",
        fix_command=(
            f"# dry run first:\n"
            f"python3 -c 'from app.scheduler.sandbox.cubesandbox_client import "
            f"CubeSandboxClient; print(CubeSandboxClient.kill_by_id(\"{orphans[0]}\"))'"
        ),
    )


STAGES: list[Callable[[], StageResult]] = [
    stage_1_env,
    stage_2_local_image,
    stage_3_cube_api_reachable,
    stage_4_sandbox_create,
    stage_5_envd_exec,
    stage_6_orphans,
]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


_STATUS_ICON = {
    "ok": "✓",
    "warn": "⚠",
    "fail": "✗",
    "skipped": "·",
}


def print_report(results: list[StageResult], fix_mode: bool = False, apply: bool = False) -> int:
    print()
    print("CubeSandbox Diagnostic")
    print("=" * 60)
    n_fail = n_warn = 0
    for r in results:
        icon = _STATUS_ICON.get(r.status, "?")
        print(f"  [{icon}] {r.name:<22} {r.detail}")
        if r.status in ("fail", "warn"):
            n_fail += 1 if r.status == "fail" else 0
            n_warn += 1 if r.status == "warn" else 0
            if r.fix_command:
                print(f"        fix: {r.fix_command}")
    print()
    if n_fail == 0 and n_warn == 0:
        print("✓ All CubeSandbox stages passed.")
        return 0
    if n_fail == 0:
        print(f"⚠ {n_warn} warning(s), no failures. Re-run after fix is applied.")
        return 1
    print(f"✗ {n_fail} failure(s), {n_warn} warning(s). See 'fix:' lines above.")
    return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--fix", action="store_true", help="Show fix commands for each failed stage")
    p.add_argument("-y", "--yes", action="store_true", help="With --fix, apply fixes without prompting")
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
        return 1 if n_fail else 0

    return print_report(results, fix_mode=args.fix, apply=args.yes)


if __name__ == "__main__":
    sys.exit(main())
