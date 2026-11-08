"""Phase 1 of the BRIDLE learning loop, part C: the daily step.

The step reads the incident log, writes ~/.memory/state/incident_patterns.json and tells the
owner ONCE -- only when a pattern is new or its count crossed a threshold, and at most one
notification per day. It reports; it never disables, excludes or re-ranks a resource.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.scheduler.incident_patterns import (
    DEFAULT_NOTIFY_THRESHOLD,
    load_state,
    scan_patterns,
)

BODY = '{"error": {"message": "prompt is too long: 195000 tokens > 163840 maximum", "code": 400}}'
ERROR = "Client error '400 Bad Request' for url x"

DAY1 = datetime(2026, 11, 8, 8, 0, tzinfo=timezone.utc)
DAY2 = DAY1 + timedelta(days=1)


def _incident(path, task_id, body=BODY, error=ERROR):
    """Append one incident row (the same shape record_incident writes)."""
    import time

    row = {
        "t": time.time(), "task_id": task_id, "role_id": "scott", "resource": "glm_5_2",
        "iteration": 1, "kind": "provider_4xx", "error": error,
        "response_body": body, "est_input_tokens": 195_000, "context_limit": 163_840,
        "largest_message_chars": 900_000, "last_tool": None,
    }
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


class _Recorder:
    """A notifier that records what it was asked to send."""

    def __init__(self):
        self.calls = []

    async def __call__(self, title, body):
        self.calls.append((title, body))


async def _scan(tmp_path, recorder=None, now=DAY1, notify_threshold=DEFAULT_NOTIFY_THRESHOLD, min_tasks=2):
    return await scan_patterns(
        incidents_path=tmp_path / "task_incidents.jsonl",
        state_path=tmp_path / "incident_patterns.json",
        min_tasks=min_tasks,
        window_days=14,
        notify_threshold=notify_threshold,
        now=now,
        notify=recorder,
    )


def _two_tasks(tmp_path):
    _incident(tmp_path / "task_incidents.jsonl", "t1")
    _incident(tmp_path / "task_incidents.jsonl", "t2")


# --------------------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------------------
async def test_the_pattern_report_is_written_even_when_nobody_is_listening(tmp_path):
    _two_tasks(tmp_path)
    summary = await _scan(tmp_path)
    state = json.loads((tmp_path / "incident_patterns.json").read_text())
    assert summary["pattern_count"] == 1
    assert summary["notified"] is False
    assert state["pattern_count"] == 1
    pattern = state["patterns"][0]
    assert pattern["resource_id"] == "glm_5_2"
    assert pattern["task_count"] == 2
    assert pattern["count"] == 2
    assert state["last_notification_date"] is None


async def test_a_malformed_line_is_counted_not_hidden(tmp_path):
    _two_tasks(tmp_path)
    with open(tmp_path / "task_incidents.jsonl", "a") as f:
        f.write('{"t": 1.0, "task_id": "t3", "res')
    summary = await _scan(tmp_path)
    assert summary["malformed_lines"] == 1
    assert summary["pattern_count"] == 1


async def test_rows_without_a_response_body_still_form_a_pattern(tmp_path):
    """The log has rows from before the body field existed -- they must still be read."""
    import time

    p = tmp_path / "task_incidents.jsonl"
    for task_id in ("t1", "t2"):
        with open(p, "a") as f:
            f.write(json.dumps({"t": time.time(), "task_id": task_id, "role_id": "scott",
                                 "resource": "glm_5_2", "iteration": 1, "kind": "provider_4xx",
                                 "error": ERROR, "largest_message_chars": 900_000}) + "\n")
    summary = await _scan(tmp_path)
    assert summary["pattern_count"] == 1


# --------------------------------------------------------------------------------------
# when the owner is told
# --------------------------------------------------------------------------------------
async def test_a_new_pattern_is_reported(tmp_path):
    _two_tasks(tmp_path)
    recorder = _Recorder()
    summary = await _scan(tmp_path, recorder)
    assert summary["notified"] is True
    assert len(recorder.calls) == 1
    title, body = recorder.calls[0]
    assert "glm_5_2" in body and "provider_4xx" in body
    assert "no resource was disabled, excluded or re-ranked" in body


async def test_the_same_pattern_is_not_reported_again(tmp_path):
    _two_tasks(tmp_path)
    recorder = _Recorder()
    await _scan(tmp_path, recorder)
    summary = await _scan(tmp_path, recorder, now=DAY2)
    assert summary["notified"] is False
    assert len(recorder.calls) == 1


async def test_a_pattern_is_reported_again_when_it_crosses_the_threshold(tmp_path):
    _two_tasks(tmp_path)
    recorder = _Recorder()
    await _scan(tmp_path, recorder)          # new pattern -> reported (count 2)
    _incident(tmp_path / "task_incidents.jsonl", "t3")
    summary = await _scan(tmp_path, recorder, now=DAY2)   # count 3 -> band 1 > band 0
    assert summary["notified"] is True
    assert len(recorder.calls) == 2


async def test_a_pattern_that_did_not_cross_the_threshold_is_not_reported_again(tmp_path):
    _two_tasks(tmp_path)
    recorder = _Recorder()
    await _scan(tmp_path, recorder)                       # reported at count 2
    _incident(tmp_path / "task_incidents.jsonl", "t3")
    await _scan(tmp_path, recorder, now=DAY2)             # count 3 -> reported
    _incident(tmp_path / "task_incidents.jsonl", "t4")
    summary = await _scan(tmp_path, recorder, now=DAY2 + timedelta(days=1))  # count 4 -> band 1, same band
    assert summary["notified"] is False
    assert len(recorder.calls) == 2


async def test_at_most_one_notification_per_day(tmp_path):
    _two_tasks(tmp_path)
    recorder = _Recorder()
    await _scan(tmp_path, recorder)                      # day 1: new pattern -> reported
    _incident(tmp_path / "task_incidents.jsonl", "t3")
    summary = await _scan(tmp_path, recorder)             # day 1 again: crossed, but the day is used
    assert summary["notified"] is False
    assert summary["daily_cap_reached"] is True
    assert len(recorder.calls) == 1
    assert summary["pending"], "the crossing must stay pending, not be dropped"


async def test_a_pending_crossing_is_reported_the_next_day(tmp_path):
    _two_tasks(tmp_path)
    recorder = _Recorder()
    await _scan(tmp_path, recorder)                      # day 1: new pattern -> reported
    _incident(tmp_path / "task_incidents.jsonl", "t3")
    await _scan(tmp_path, recorder)                      # day 1: suppressed by the daily cap
    summary = await _scan(tmp_path, recorder, now=DAY2)   # day 2: reported, not dropped
    assert summary["notified"] is True
    assert len(recorder.calls) == 2


async def test_the_report_is_written_before_the_notification_is_sent(tmp_path):
    _two_tasks(tmp_path)

    async def _boom(title, body):
        raise RuntimeError("the notification channel is down")

    with pytest.raises(RuntimeError):
        await _scan(tmp_path, _boom)
    state = json.loads((tmp_path / "incident_patterns.json").read_text())
    assert state["pattern_count"] == 1
    assert state["last_notification_date"] is None


async def test_the_state_file_remembers_what_was_reported(tmp_path):
    _two_tasks(tmp_path)
    recorder = _Recorder()
    await _scan(tmp_path, recorder)
    state = load_state(tmp_path / "incident_patterns.json")
    assert state["last_notification_date"] == DAY1.date().isoformat()
    assert len(state["notified"]) == 1
    entry = next(iter(state["notified"].values()))
    assert entry["notified_count"] == 2


# --------------------------------------------------------------------------------------
# the scheduled step
# --------------------------------------------------------------------------------------
def test_the_handler_is_registered():
    from app.scheduler.handlers import build_registry
    from app.scheduler.models import TaskType

    assert TaskType.INCIDENT_PATTERNS.value == "incident_patterns"
    assert TaskType.INCIDENT_PATTERNS in build_registry()._handlers


def test_the_daily_step_is_seeded_from_the_scheduler_config():
    from app.config.config_loader import load_layered_json_config

    cfg = load_layered_json_config("config/scheduler_config.json")
    entry = next((t for t in cfg["default_tasks"] if t["id"] == "incident_patterns_daily"), None)
    assert entry is not None, "the daily incident-pattern step must be seeded"
    assert entry["type"] == "incident_patterns"
    assert entry.get("enabled", True) is True, "it runs once a day by default"
    assert entry["cron"] == "0 8 * * *"
    assert entry["config"]["min_tasks"] == 2
    assert entry["config"]["window_days"] == 14
    assert entry["config"]["notify_threshold"] == 3


async def test_the_handler_runs_the_scan_and_returns_the_summary(monkeypatch, tmp_path):
    from app.scheduler.executor_registry import ExecutorContext
    from app.scheduler.handlers.incident_patterns import IncidentPatternsHandler
    from app.scheduler.models import Task, TaskType

    seen = {}

    async def _fake_scan(**kwargs):
        seen.update(kwargs)
        return {"pattern_count": 0, "reportable": [], "notified": False, "pending": [],
                "state_path": str(tmp_path / "incident_patterns.json")}

    monkeypatch.setattr("app.scheduler.incident_patterns.scan_patterns", _fake_scan)
    task = Task(id="incident_patterns_daily", type=TaskType.INCIDENT_PATTERNS,
                config={"min_tasks": 3, "window_days": 7, "notify_threshold": 5})
    result = await IncidentPatternsHandler().execute(task, ExecutorContext())
    assert result.success is True
    assert result.metrics["pattern_count"] == 0
    assert seen["min_tasks"] == 3 and seen["window_days"] == 7 and seen["notify_threshold"] == 5


def test_the_step_cannot_change_routing():
    """The reader of the incident log must not reach into the pool: it reports, it does not
    disable, exclude or re-rank a resource."""
    import ast
    import inspect

    import app.scheduler.incident_patterns as module

    tree = ast.parse(inspect.getsource(module))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported += [alias.name for alias in node.names]
    assert not any("resource_pool" in name for name in imported), \
        "the incident-pattern step must not talk to the resource pool"

    called = [node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    for forbidden in ("disable", "exclude", "set_priority", "acquire", "update_config"):
        assert not any(forbidden in name for name in called), \
            f"the incident-pattern step must not call {forbidden!r} on anything"
