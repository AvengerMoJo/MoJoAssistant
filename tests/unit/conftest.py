"""Keep unit tests away from the user's real ~/.memory.

ResourceManager persists usage, meta, smoke history and known-resource ids to files whose
paths are class attributes defaulting to ~/.memory. Tests that built a manager without
patching them wrote test data into -- and, with prune_orphan_usage(), archived the real
call history out of -- the live files (found 2026-10-08).
"""
import pytest

from app.scheduler.resource_pool import ResourceManager


@pytest.fixture(autouse=True)
def _isolate_resource_manager_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ResourceManager, "USAGE_FILE", tmp_path / "resource_pool_usage.json")
    monkeypatch.setattr(ResourceManager, "META_FILE", tmp_path / "resource_pool_meta.json")
    monkeypatch.setattr(ResourceManager, "SMOKE_LOG_FILE", tmp_path / "resource_pool_smoke_log.jsonl")
    monkeypatch.setattr(ResourceManager, "KNOWN_IDS_FILE", tmp_path / "resource_pool_known_ids.json")
    yield
