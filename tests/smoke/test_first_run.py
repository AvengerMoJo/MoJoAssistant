"""Smoke tests for app/config/first_run.py"""

import json
from pathlib import Path

import pytest

from app.config.first_run import (
    OWNER_PROFILE_TEMPLATE,
    create_owner_profile,
    load_owner_profile,
    unpack_bundled_roles,
)


# ---------------------------------------------------------------------------
# unpack_bundled_roles
# ---------------------------------------------------------------------------


def test_unpack_bundled_roles_copies_roles(tmp_path: Path) -> None:
    """Roles from config/roles/ should be copied into tmp memory dir."""
    unpacked = unpack_bundled_roles(tmp_path)
    roles_dir = tmp_path / "roles"

    assert roles_dir.is_dir()
    # At minimum ahman and carl should be present (we just bundled them)
    assert "ahman" in unpacked
    assert "carl" in unpacked
    assert (roles_dir / "ahman.json").exists()
    assert (roles_dir / "carl.json").exists()


def test_unpack_bundled_roles_idempotent(tmp_path: Path) -> None:
    """Running unpack twice must not overwrite the first copy."""
    # First run
    unpack_bundled_roles(tmp_path)

    # Tamper with an unpacked file so we can detect an overwrite
    target = tmp_path / "roles" / "ahman.json"
    original_mtime = target.stat().st_mtime
    target.write_text('{"tampered": true}', encoding="utf-8")

    # Second run
    second_unpacked = unpack_bundled_roles(tmp_path)

    # ahman should NOT be in second_unpacked (already existed)
    assert "ahman" not in second_unpacked

    # File content must still be the tampered version
    data = json.loads(target.read_text())
    assert data == {"tampered": True}


def test_unpack_bundled_roles_skips_example_files(tmp_path: Path) -> None:
    """Files ending in .example must not be copied."""
    unpack_bundled_roles(tmp_path)
    roles_dir = tmp_path / "roles"
    example_files = list(roles_dir.glob("*.example"))
    assert example_files == [], f"Unexpected .example files: {example_files}"


# ---------------------------------------------------------------------------
# create_owner_profile
# ---------------------------------------------------------------------------


def test_create_owner_profile_creates_file(tmp_path: Path) -> None:
    """create_owner_profile() should write owner_profile.json with expected keys."""
    path = create_owner_profile(tmp_path)

    assert path == tmp_path / "owner_profile.json"
    assert path.exists()

    data = json.loads(path.read_text())
    # Every key from OWNER_PROFILE_TEMPLATE must be present
    for key in OWNER_PROFILE_TEMPLATE:
        assert key in data, f"Missing key: {key}"


def test_create_owner_profile_applies_overrides(tmp_path: Path) -> None:
    """Overrides should be reflected in the written file."""
    create_owner_profile(
        tmp_path,
        overrides={"name": "TestUser", "timezone": "UTC"},
    )
    data = json.loads((tmp_path / "owner_profile.json").read_text())
    assert data["name"] == "TestUser"
    assert data["timezone"] == "UTC"


def test_create_owner_profile_does_not_overwrite(tmp_path: Path) -> None:
    """create_owner_profile() must never overwrite an existing file."""
    profile_path = tmp_path / "owner_profile.json"
    profile_path.write_text('{"protected": true}', encoding="utf-8")

    create_owner_profile(tmp_path, overrides={"name": "ShouldNotAppear"})

    data = json.loads(profile_path.read_text())
    assert data == {"protected": True}


# ---------------------------------------------------------------------------
# load_owner_profile
# ---------------------------------------------------------------------------


def test_load_owner_profile_returns_empty_dict_when_missing(tmp_path: Path) -> None:
    """load_owner_profile() should return {} when file does not exist."""
    result = load_owner_profile(tmp_path)
    assert result == {}


def test_load_owner_profile_returns_data_when_present(tmp_path: Path) -> None:
    """load_owner_profile() should return parsed JSON when file exists."""
    create_owner_profile(tmp_path, overrides={"name": "Alex"})
    data = load_owner_profile(tmp_path)
    assert data["name"] == "Alex"
