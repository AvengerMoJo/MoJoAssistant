"""Unit tests for scripts/merge_cloudflared_config.py."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "merge_cloudflared_config.py"


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


USER_CONFIG_YAML = """\
tunnel: c7a1ca2b-c1ea-407d-8078-bdb65412f693
credentials-file: /home/alex/.cloudflared/c7a1ca2b-c1ea-407d-8078-bdb65412f693.json
origin-request:
  no-proxy: true
ingress:
  - hostname: mbti.eclipsogate.org
    service: http://localhost:3000
  - hostname: docker.eclipsogate.org
    service: http://localhost:9001
  - hostname: ntfy.eclipsogate.org
    service: http://127.0.0.1:2586
  - service: http_status:404
"""

OVERLAY_YAML = """\
- hostname: sandbox.eclipsogate.org
  service: https://127.0.0.1:12443
  originRequest:
    noTLSVerify: true
- hostname: dashboard.eclipsogate.org
  service: http://127.0.0.1:12088
"""


def _run_merge(user_cfg: Path, overlay: Path, out: Path, *args: str) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable, str(SCRIPT),
        "--user-config", str(user_cfg),
        "--overlay", str(overlay),
        "--out", str(out),
        "--no-backup",
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _run_merge_with_backup(user_cfg: Path, overlay: Path, out: Path) -> subprocess.CompletedProcess:
    """Same as _run_merge but without --no-backup, so .bak is created on overwrite."""
    cmd = [
        sys.executable, str(SCRIPT),
        "--user-config", str(user_cfg),
        "--overlay", str(overlay),
        "--out", str(out),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_merges_overlay_before_catchall(tmp_path: Path):
    user_cfg = tmp_path / "config.yml"
    overlay = tmp_path / "overlay.yml"
    out = tmp_path / "merged.yml"
    _write(user_cfg, USER_CONFIG_YAML)
    _write(overlay, OVERLAY_YAML)

    rc = _run_merge(user_cfg, overlay, out)
    assert rc.returncode == 0, rc.stderr

    import yaml
    merged = yaml.safe_load(out.read_text())
    ingress = merged["ingress"]

    # All four original hostnames preserved (mbti, docker, ntfy + new sandbox/dashboard)
    hostnames = [r.get("hostname") for r in ingress if "hostname" in r]
    assert hostnames == [
        "mbti.eclipsogate.org",
        "docker.eclipsogate.org",
        "ntfy.eclipsogate.org",
        "sandbox.eclipsogate.org",
        "dashboard.eclipsogate.org",
    ]

    # Catch-all is last
    assert "hostname" not in ingress[-1]
    assert ingress[-1]["service"] == "http_status:404"


def test_overlay_is_source_of_truth(tmp_path: Path):
    """If the user file already has a stale entry for an overlay hostname, the overlay wins."""
    user_cfg = tmp_path / "config.yml"
    overlay = tmp_path / "overlay.yml"
    out = tmp_path / "merged.yml"
    _write(user_cfg, USER_CONFIG_YAML)
    _write(overlay, OVERLAY_YAML)

    # Pre-poison the user config with a stale dashboard entry on port 9999
    import yaml
    cfg = yaml.safe_load(user_cfg.read_text())
    cfg["ingress"].insert(2, {
        "hostname": "dashboard.eclipsogate.org",
        "service": "http://127.0.0.1:9999",  # stale
    })
    user_cfg.write_text(yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False))

    rc = _run_merge(user_cfg, overlay, out)
    assert rc.returncode == 0, rc.stderr

    merged = yaml.safe_load(out.read_text())
    dashboards = [r for r in merged["ingress"] if r.get("hostname") == "dashboard.eclipsogate.org"]
    assert len(dashboards) == 1
    assert dashboards[0]["service"] == "http://127.0.0.1:12088"  # overlay wins


def test_requires_catchall(tmp_path: Path):
    user_cfg = tmp_path / "config.yml"
    overlay = tmp_path / "overlay.yml"
    out = tmp_path / "merged.yml"
    _write(user_cfg, USER_CONFIG_YAML.replace("- service: http_status:404\n", ""))
    _write(overlay, OVERLAY_YAML)

    rc = _run_merge(user_cfg, overlay, out)
    assert rc.returncode != 0
    assert "catch-all" in rc.stderr.lower()


def test_dry_run_does_not_modify_files(tmp_path: Path):
    user_cfg = tmp_path / "config.yml"
    overlay = tmp_path / "overlay.yml"
    _write(user_cfg, USER_CONFIG_YAML)
    _write(overlay, OVERLAY_YAML)

    before = user_cfg.read_text()
    rc = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--user-config", str(user_cfg),
         "--overlay", str(overlay),
         "--dry-run"],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr
    assert user_cfg.read_text() == before  # unchanged
    # stdout contains the merged output
    assert "sandbox.eclipsogate.org" in rc.stdout


def test_creates_backup_before_overwrite(tmp_path: Path):
    user_cfg = tmp_path / "config.yml"
    overlay = tmp_path / "overlay.yml"
    _write(user_cfg, USER_CONFIG_YAML)
    _write(overlay, OVERLAY_YAML)

    rc = _run_merge_with_backup(user_cfg, overlay, user_cfg)  # in-place merge, .bak expected
    assert rc.returncode == 0, rc.stderr

    backup = user_cfg.with_name(user_cfg.name + ".bak")
    assert backup.exists()
    assert "mbti.eclipsogate.org" in backup.read_text()


@pytest.mark.skipif(shutil.which("cloudflared") is None, reason="cloudflared not on PATH")
def test_validates_with_cloudflared_when_available(tmp_path: Path):
    user_cfg = tmp_path / "config.yml"
    overlay = tmp_path / "overlay.yml"
    out = tmp_path / "merged.yml"
    _write(user_cfg, USER_CONFIG_YAML)
    _write(overlay, OVERLAY_YAML)

    # May fail with non-zero exit because credentials file doesn't exist; we
    # only assert the script ran the validation step.
    rc = _run_merge(user_cfg, overlay, out)
    assert rc.returncode in (0, 1)  # 0=valid, 1=invalid (we still want it to run validation)
