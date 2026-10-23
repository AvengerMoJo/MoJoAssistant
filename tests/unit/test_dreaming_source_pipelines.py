"""Only the owner-conversation pipeline is shared; other sources get a pipeline built for their own scope."""
from app.scheduler.executor_registry import ExecutorContext


def _ctx():
    ctx = ExecutorContext.__new__(ExecutorContext)
    ctx._dreaming_pipeline = None
    ctx._cached_quality_level = None
    ctx.logger = None
    ctx.built = []
    ctx._build_dreaming_llm = lambda source="conversation", role_id=None: ctx.built.append((source, role_id)) or object()
    return ctx


def test_task_output_gets_its_own_pipeline_and_leaves_the_shared_one_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path))
    ctx = _ctx()
    shared = ctx.get_dreaming_pipeline("basic")
    out = ctx.get_dreaming_pipeline("basic", source="task_output", role_id="paul")
    assert out is not shared
    assert ctx.get_dreaming_pipeline("basic") is shared
    assert ctx.built == [("conversation", None), ("task_output", "paul")]


def test_a_role_store_with_conversation_source_is_built_for_conversation(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path))
    ctx = _ctx()
    ctx.get_dreaming_pipeline("basic", storage_path=tmp_path / "r", role_id="scott")
    assert ctx.built == [("conversation", "scott")]
