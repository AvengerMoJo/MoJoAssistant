"""A role-scoped dream must never repoint the shared global pipeline (2026-10-10: a global dream's archive
landed in roles/scott/knowledge_units because chat_bridge had reassigned the shared pipeline's .storage)."""
import re
from pathlib import Path
from unittest.mock import patch

from app.scheduler.executor_registry import ExecutorContext


def _ctx(tmp_path):
    ctx = ExecutorContext.__new__(ExecutorContext)
    ctx._dreaming_pipeline = None
    ctx._cached_quality_level = None
    ctx.logger = None
    ctx._build_dreaming_llm = lambda: object()
    return ctx


def test_role_pipeline_is_separate_and_global_one_is_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path))
    ctx = _ctx(tmp_path)
    shared = ctx.get_dreaming_pipeline("basic")
    shared_store = shared.storage
    role_store = tmp_path / "roles" / "scott" / "knowledge_units"
    role = ctx.get_dreaming_pipeline("basic", storage_path=role_store)

    assert role is not shared
    assert shared.storage is shared_store                      # the shared pipeline was not repointed
    assert ctx.get_dreaming_pipeline("basic") is shared        # and is still the cached global one
    assert Path(role.storage.storage_path).resolve() == role_store.resolve()
    assert Path(shared.storage.storage_path).resolve() != role_store.resolve()


def test_two_roles_get_two_pipelines(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path))
    ctx = _ctx(tmp_path)
    a = ctx.get_dreaming_pipeline("basic", storage_path=tmp_path / "a")
    b = ctx.get_dreaming_pipeline("basic", storage_path=tmp_path / "b")
    assert a is not b and a.storage is not b.storage


def test_handler_never_assigns_pipeline_storage():
    src = Path("app/scheduler/handlers/dreaming.py").read_text()
    assert not re.search(r"pipeline\.storage\s*=", src), "mutating the shared pipeline's storage races across tasks"
