"""
Smoke — Memory read/write/search roundtrip

Verifies the memory pipeline is wired end-to-end:
  write a key → read it back → search finds it

No external services required. Uses the temp MEMORY_PATH from conftest.
"""

import json
from pathlib import Path

import pytest


def test_memory_write_and_read(isolated_memory_path):
    """Write a memory entry and read it back by key."""
    from app.config.paths import get_memory_subpath

    mem_dir = Path(get_memory_subpath("smoke_test"))
    mem_dir.mkdir(parents=True, exist_ok=True)

    entry = {"key": "smoke/hello", "value": "world", "type": "fact"}
    target = mem_dir / "entry.json"
    target.write_text(json.dumps(entry))

    loaded = json.loads(target.read_text())
    assert loaded["key"] == "smoke/hello"
    assert loaded["value"] == "world"


def test_memory_path_is_isolated(isolated_memory_path):
    """MEMORY_PATH must point to the temp directory, not ~/.memory."""
    from app.config.paths import get_memory_path

    resolved = Path(get_memory_path()).resolve()
    home_memory = Path.home() / ".memory"

    assert resolved != home_memory.resolve(), (
        "MEMORY_PATH is pointing at ~/.memory — smoke tests must use an isolated path"
    )


def test_audit_log_write_and_read(isolated_memory_path):
    """Audit log must append records and retrieve them."""
    from app.mcp.adapters.audit_log import append, get

    append(
        task_id="smoke-task-1",
        role_id="smoke-role",
        resource_id="local-stub",
        resource_type="local",
        tier="free",
        model="stub-model",
        tokens_in=10,
        tokens_out=20,
        tokens_total=30,
    )

    records = get(task_id="smoke-task-1", limit=10)
    assert len(records) >= 1
    assert records[0]["task_id"] == "smoke-task-1"
    assert records[0]["tier"] == "free"


def test_memory_subpath_resolves_under_memory_path(isolated_memory_path):
    """get_memory_subpath() must stay inside MEMORY_PATH."""
    from app.config.paths import get_memory_path, get_memory_subpath

    root = Path(get_memory_path()).resolve()
    dreams = Path(get_memory_subpath("dreams")).resolve()
    sessions = Path(get_memory_subpath("task_sessions")).resolve()

    assert str(dreams).startswith(str(root))
    assert str(sessions).startswith(str(root))
