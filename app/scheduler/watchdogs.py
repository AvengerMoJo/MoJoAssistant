"""Deterministic watchdogs: notice when the automation itself has stopped, without using an LLM.

2026-10-08 review (F6): the Project Sentinel -- the designed guard against false "done" claims --
had not completed a normal run for at least a week and nobody was told; global dreaming "completed"
nightly while its newest archive was 8 days old. A watcher that is itself an LLM job cannot report
its own death, so these checks are plain code over durable evidence (run ledger, queue, project
files, archive timestamps) and deliver through the normal event/notification path.

Pure functions: they take evidence and return findings. Alert de-duplication and delivery live in
the scheduler.
"""
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.scheduler.run_ledger import RunLedger
from app.scheduler.triggers import CronTrigger


def cron_period_seconds(cron_expression: str, now: datetime) -> float:
    """Typical gap between two firings of a cron expression."""
    trigger = CronTrigger(cron_expression)
    first = trigger.get_next_run_time(after=now)
    second = trigger.get_next_run_time(after=first)
    return (second - first).total_seconds()


def _parse(ts: Any) -> Optional[datetime]:
    """datetime or ISO string (queue fields hold either) -> datetime, else None."""
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(ts) if ts else None
    except (TypeError, ValueError):
        return None


def stale_watchers(
    tasks: Iterable[Any],
    ledger: RunLedger,
    now: datetime,
    factor: float = 2.0,
    grace_seconds: float = 3600.0,
) -> List[Dict[str, Any]]:
    """Recurring tasks whose last success is older than factor x their period (+ grace).

    Evidence for "last success" is the later of the run ledger and the queue's own
    last_completed_at; a task with neither is measured from its creation time, so a job that has
    NEVER succeeded is caught once it has been due for long enough.
    """
    findings = []
    for t in tasks:
        if not getattr(t, "cron_expression", None):
            continue
        status = getattr(t.status, "value", t.status)
        if status == "running":
            continue
        try:
            period = cron_period_seconds(t.cron_expression, now)
        except Exception:
            continue  # an invalid cron is a different problem, reported elsewhere
        ledger_ok = _parse((ledger.last_success(t.id) or {}).get("ended_at"))
        queue_ok = _parse(getattr(t, "last_completed_at", None))
        candidates = [x for x in (ledger_ok, queue_ok) if x]
        last_ok = max(candidates) if candidates else _parse(getattr(t, "created_at", None))
        if last_ok is None:
            continue
        age = (now - last_ok).total_seconds()
        if age <= factor * period + grace_seconds:
            continue
        last_attempt = (ledger.recent(t.id, limit=1) or [None])[0]
        findings.append({
            "task_id": t.id,
            "role_id": (t.config or {}).get("role_id"),
            "status": status,
            "period_hours": round(period / 3600, 1),
            "last_success": last_ok.isoformat(timespec="seconds") if candidates else None,
            "hours_since_success": round(age / 3600, 1),
            "ever_succeeded": bool(candidates),
            "last_attempt": (
                {"at": last_attempt.get("ended_at"), "outcome": last_attempt.get("outcome"),
                 "error_class": last_attempt.get("error_class"), "error": last_attempt.get("error")}
                if last_attempt else None
            ),
        })
    return findings


def stalled_project_items(projects: Iterable[Any], now: datetime, in_progress_days: int = 7,
                          blocked_days: int = 14) -> List[Dict[str, Any]]:
    """Items that claim to be moving but have not been touched, in active projects.

    `todo` is backlog and is not flagged. `in_progress` untouched for in_progress_days is stalled;
    `blocked` untouched for blocked_days is waiting on a decision nobody has made.
    """
    out = []
    for p in projects:
        if getattr(p, "status", "active") != "active":
            continue
        for item in p.items:
            updated = _parse(item.updated_at)
            if updated is None:
                continue
            limit = {"in_progress": in_progress_days, "blocked": blocked_days}.get(item.status)
            if limit is None:
                continue
            idle = now - updated
            if idle > timedelta(days=limit):
                out.append({"project_id": p.id, "owner": p.owner_role_id, "item_id": item.id,
                            "status": item.status, "idle_days": idle.days, "title": item.title[:100]})
    return out


def dreams_stale(dreams_dir: Path, now: datetime, max_age_days: float = 3.0) -> Optional[Dict[str, Any]]:
    """The memory-consolidation output has stopped appearing (newest archive older than max_age_days)."""
    dreams_dir = Path(dreams_dir)
    if not dreams_dir.exists():
        return None
    newest = None
    for entry in dreams_dir.iterdir():
        if entry.name.startswith("test_"):
            continue
        mtime = datetime.fromtimestamp(entry.stat().st_mtime)
        if newest is None or mtime > newest[0]:
            newest = (mtime, entry.name)
    if newest is None:
        return None
    age = now - newest[0]
    if age > timedelta(days=max_age_days):
        return {"newest_archive": newest[1], "age_days": round(age.total_seconds() / 86400, 1)}
    return None


def waiting_for_human(
    tasks: Iterable[Any],
    ledger: RunLedger,
    now: datetime,
    remind_hours: float = 24.0,
    escalate_hours: float = 72.0,
) -> List[Dict[str, Any]]:
    """Tasks paused on a human answer, oldest first, with how long they have waited.

    Waiting began at the latest 'waiting_for_input' ledger entry, else the HITL post stamp, else the
    task's start. A task whose parent is no longer waiting or running is flagged `orphaned`: nobody is
    left to use the answer, so the useful action is to cancel it. Nothing is cancelled automatically.
    """
    by_id = {t.id: t for t in tasks}
    out = []
    for t in by_id.values():
        if getattr(t.status, "value", t.status) != "waiting_for_input":
            continue
        entry = next((e for e in ledger.recent(t.id, limit=20) if e.get("outcome") == "waiting_for_input"), None)
        since = (_parse((entry or {}).get("ended_at"))
                 or _parse((t.config or {}).get("_hitl_posted_at"))
                 or _parse(getattr(t, "started_at", None)) or _parse(getattr(t, "created_at", None)))
        if since is None:
            continue
        hours = (now - since).total_seconds() / 3600
        if hours < remind_hours:
            continue
        parent_id = getattr(t, "parent_task_id", None)
        parent = by_id.get(parent_id) if parent_id else None
        parent_status = getattr(getattr(parent, "status", None), "value", None)
        out.append({
            "task_id": t.id,
            "hours_waiting": round(hours, 1),
            "level": "escalated" if hours >= escalate_hours else "reminder",
            "orphaned": bool(parent_id) and parent_status not in ("running", "waiting_for_input"),
            "parent_task_id": parent_id,
            "question": str(t.pending_question or "")[:240],
            "choices": (t.config or {}).get("pending_options"),
        })
    out.sort(key=lambda f: -f["hours_waiting"])
    return out
