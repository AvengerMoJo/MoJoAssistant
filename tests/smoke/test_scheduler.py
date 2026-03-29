"""
Smoke — Scheduler lifecycle (no network, no LLM)

Verifies that TaskQueue and Task models work end-to-end:
  add a task → retrieve it → check status transitions

Uses isolated_memory_path from conftest so nothing touches ~/.memory.
"""

import pytest

from app.scheduler.models import Task, TaskStatus, TaskPriority, TaskType, TaskResult


def _make_task(task_id: str = "smoke-task-1", task_type: TaskType = TaskType.CUSTOM) -> Task:
    return Task(
        id=task_id,
        type=task_type,
        priority=TaskPriority.LOW,
        description="smoke test task",
        created_by="smoke",
    )


def test_task_model_roundtrip():
    """Task serializes to dict and deserializes back without data loss."""
    task = _make_task()
    d = task.to_dict()
    restored = Task.from_dict(d)

    assert restored.id == task.id
    assert restored.type == task.type
    assert restored.priority == task.priority
    assert restored.status == TaskStatus.PENDING
    assert restored.description == task.description


def test_task_is_due_immediate():
    """A task with no schedule is immediately due."""
    task = _make_task()
    assert task.is_due() is True


def test_task_status_transitions():
    """Mark-started and mark-completed update status and timestamps."""
    task = _make_task()
    assert task.status == TaskStatus.PENDING
    assert task.started_at is None

    task.mark_started()
    assert task.status == TaskStatus.RUNNING
    assert task.started_at is not None

    result = TaskResult(success=True, output_file=None)
    task.mark_completed(result)
    assert task.status == TaskStatus.COMPLETED
    assert task.completed_at is not None
    assert task.result.success is True


def test_task_queue_add_and_get(isolated_memory_path, tmp_path):
    """Add a task to the queue and retrieve it by ID."""
    from app.scheduler.queue import TaskQueue

    storage = tmp_path / "tasks.json"
    queue = TaskQueue(storage_path=str(storage))

    task = _make_task("q-smoke-1")
    added = queue.add(task)
    assert added is True

    retrieved = queue.get("q-smoke-1")
    assert retrieved is not None
    assert retrieved.id == "q-smoke-1"
    assert retrieved.status == TaskStatus.PENDING


def test_task_queue_get_next_priority(isolated_memory_path, tmp_path):
    """get_next() returns the highest-priority pending task."""
    from app.scheduler.queue import TaskQueue

    storage = tmp_path / "tasks_prio.json"
    queue = TaskQueue(storage_path=str(storage))

    low = _make_task("low-1")
    low.priority = TaskPriority.LOW

    high = _make_task("high-1")
    high.priority = TaskPriority.HIGH

    queue.add(low)
    queue.add(high)

    next_task = queue.get_next()
    assert next_task is not None
    assert next_task.id == "high-1"


def test_task_queue_persistence(isolated_memory_path, tmp_path):
    """Tasks survive a queue reload from disk."""
    from app.scheduler.queue import TaskQueue

    storage = tmp_path / "persist.json"

    q1 = TaskQueue(storage_path=str(storage))
    q1.add(_make_task("persist-1"))

    q2 = TaskQueue(storage_path=str(storage))
    restored = q2.get("persist-1")
    assert restored is not None
    assert restored.description == "smoke test task"


def test_task_queue_statistics(isolated_memory_path, tmp_path):
    """get_statistics() returns a dict with at least a total count."""
    from app.scheduler.queue import TaskQueue

    storage = tmp_path / "stats.json"
    queue = TaskQueue(storage_path=str(storage))
    queue.add(_make_task("stat-1"))

    stats = queue.get_statistics()
    assert isinstance(stats, dict)
    assert stats.get("total", 0) >= 1
