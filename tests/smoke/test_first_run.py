"""Smoke tests for app/config/first_run.py"""

import json
from pathlib import Path

import pytest

from app.config.first_run import (
    BACKEND_CATALOG,
    OWNER_PROFILE_TEMPLATE,
    _DEMO_TASKS,
    create_owner_profile,
    detect_llm_backends,
    load_owner_profile,
    recommend_model,
    seed_demo_tasks,
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
    # At minimum researcher and developer should be present (bundled in config/roles/)
    assert "researcher" in unpacked
    assert "developer" in unpacked
    assert (roles_dir / "researcher.json").exists()
    assert (roles_dir / "developer.json").exists()


def test_unpack_bundled_roles_idempotent(tmp_path: Path) -> None:
    """Running unpack twice must not overwrite the first copy."""
    # First run
    unpack_bundled_roles(tmp_path)

    # Tamper with an unpacked file so we can detect an overwrite
    target = tmp_path / "roles" / "researcher.json"
    original_mtime = target.stat().st_mtime
    target.write_text('{"tampered": true}', encoding="utf-8")

    # Second run
    second_unpacked = unpack_bundled_roles(tmp_path)

    # researcher should NOT be in second_unpacked (already existed)
    assert "researcher" not in second_unpacked

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


# ---------------------------------------------------------------------------
# detect_llm_backends / recommend_model
# ---------------------------------------------------------------------------


def test_detect_llm_backends_returns_list() -> None:
    """detect_llm_backends() must always return a list (even if nothing is running)."""
    result = detect_llm_backends(timeout=0.1)
    assert isinstance(result, list)


def test_detect_llm_backends_entries_are_known_backends() -> None:
    """Every detected entry must be a dict with at least id/label/base_url keys."""
    result = detect_llm_backends(timeout=0.1)
    catalog_ids = {b["id"] for b in BACKEND_CATALOG}
    for entry in result:
        assert "id" in entry
        assert "label" in entry
        assert "base_url" in entry
        assert entry["id"] in catalog_ids


def test_recommend_model_returns_smallest_when_zero_vram() -> None:
    """With 0 VRAM, recommend_model should return the smallest model (min_vram_gb=0)."""
    ollama = next(b for b in BACKEND_CATALOG if b["id"] == "ollama")
    rec = recommend_model(ollama, vram_gb=0)
    assert rec["min_vram_gb"] == 0


def test_recommend_model_respects_vram_ceiling() -> None:
    """With 8 GB VRAM, should not recommend a model requiring > 8 GB."""
    ollama = next(b for b in BACKEND_CATALOG if b["id"] == "ollama")
    rec = recommend_model(ollama, vram_gb=8)
    assert rec["min_vram_gb"] <= 8


def test_recommend_model_picks_highest_fitting_tier() -> None:
    """With 16 GB VRAM, should recommend the 16 GB tier, not 8 GB or lower."""
    ollama = next(b for b in BACKEND_CATALOG if b["id"] == "ollama")
    rec = recommend_model(ollama, vram_gb=16)
    assert rec["min_vram_gb"] == 16


def test_backend_catalog_all_have_required_fields() -> None:
    """Every entry in BACKEND_CATALOG must have the required fields."""
    required = {"id", "label", "host", "port", "base_url", "model_ladder", "default_model"}
    for backend in BACKEND_CATALOG:
        missing = required - set(backend.keys())
        assert not missing, f"Backend '{backend.get('id')}' missing fields: {missing}"


# ---------------------------------------------------------------------------
# seed_demo_tasks
# ---------------------------------------------------------------------------


def test_seed_demo_tasks_creates_task_files(tmp_path: Path) -> None:
    """seed_demo_tasks() should write one JSON file per demo task."""
    seeded = seed_demo_tasks(tmp_path)
    tasks_dir = tmp_path / "tasks"

    assert len(seeded) == len(_DEMO_TASKS)
    for task_id in seeded:
        assert (tasks_dir / f"{task_id}.json").exists()


def test_seed_demo_tasks_files_are_valid_json(tmp_path: Path) -> None:
    """Each seeded task file must be valid JSON with required keys."""
    seed_demo_tasks(tmp_path)
    tasks_dir = tmp_path / "tasks"
    required_keys = {"id", "type", "status", "config", "created_at"}
    for task_file in tasks_dir.glob("*.json"):
        data = json.loads(task_file.read_text())
        missing = required_keys - set(data.keys())
        assert not missing, f"{task_file.name} missing keys: {missing}"
        assert data["status"] == "pending"


def test_seed_demo_tasks_idempotent(tmp_path: Path) -> None:
    """Running seed_demo_tasks twice must not overwrite existing task files."""
    seed_demo_tasks(tmp_path)
    # Tamper with a file
    tasks_dir = tmp_path / "tasks"
    first_file = next(tasks_dir.glob("*.json"))
    first_file.write_text('{"tampered": true}', encoding="utf-8")

    second_seeded = seed_demo_tasks(tmp_path)
    # Nothing should be re-seeded
    assert len(second_seeded) == 0
    # Tampered file must still be tampered
    assert json.loads(first_file.read_text()) == {"tampered": True}


def test_seed_demo_tasks_each_has_role_id(tmp_path: Path) -> None:
    """Every demo task config must specify a role_id."""
    seed_demo_tasks(tmp_path)
    tasks_dir = tmp_path / "tasks"
    for task_file in tasks_dir.glob("*.json"):
        data = json.loads(task_file.read_text())
        assert "role_id" in data.get("config", {}), f"{task_file.name} missing config.role_id"


# ---------------------------------------------------------------------------
# End-to-end: clean tmp directory
# ---------------------------------------------------------------------------


def test_end_to_end_clean_install(tmp_path: Path) -> None:
    """Full first-run on a clean tmp directory produces all expected artefacts."""
    memory_path = tmp_path / ".memory"

    # 1. Owner profile
    create_owner_profile(memory_path, overrides={"name": "TestUser", "timezone": "UTC"})
    assert (memory_path / "owner_profile.json").exists()
    profile = json.loads((memory_path / "owner_profile.json").read_text())
    assert profile["name"] == "TestUser"
    assert profile["timezone"] == "UTC"

    # 2. Roles unpacked
    unpacked = unpack_bundled_roles(memory_path)
    assert len(unpacked) >= 3  # researcher, developer, network_admin at minimum
    for role_id in unpacked:
        assert (memory_path / "roles" / f"{role_id}.json").exists()

    # 3. Demo tasks seeded
    scheduler_storage = memory_path / "scheduler"
    seeded = seed_demo_tasks(scheduler_storage)
    assert len(seeded) == len(_DEMO_TASKS)
    tasks_dir = scheduler_storage / "tasks"
    for task_id in seeded:
        task_data = json.loads((tasks_dir / f"{task_id}.json").read_text())
        assert task_data["status"] == "pending"
        assert task_data["config"].get("source") == "first_run"

    # 4. Second run is fully idempotent
    assert unpack_bundled_roles(memory_path) == []
    assert seed_demo_tasks(scheduler_storage) == []
    create_owner_profile(memory_path, overrides={"name": "ShouldNotAppear"})
    assert json.loads((memory_path / "owner_profile.json").read_text())["name"] == "TestUser"
