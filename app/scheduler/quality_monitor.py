"""
Quality Monitor — deterministic task-health watchdog.

Spec: docs/specs/quality_monitor_spec.md
Origin: task 28eb4899 (role_id=paul, 2026-09-17) self-reported
success=true after writing a PRD, without ever meeting its own stated
"Done when: a PR exists..." condition. Nothing verified the claim before
the task closed as a clean success.

Deliberately NOT an agentic/LLM role. A watchdog that needs an LLM to
reason about stuck LLM-driven tasks could get stuck the same way its
subjects do — every check here is plain Python: state, timestamps, and
direct verification of a task's own stated completion condition (never
by re-asking the agent that already claimed success).

Called periodically from Scheduler._ticker_loop (see core.py), not run
as its own scheduled task, so it has no failure mode of its own to watch.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.config.paths import get_memory_subpath
from app.scheduler.models import Task, TaskPriority, TaskStatus, TaskType
from app.scheduler.queue import TaskQueue

RESTART_CAP = 2
STUCK_GRACE_SECONDS = 300  # slack beyond a task's own max_duration_seconds
WAITING_TOO_LONG_HOURS = 24
QM_RESTART_COUNT_KEY = "_qm_restart_count"
QM_ORIGIN_KEY = "_qm_restarted_from"
QM_ESCALATED_KEY = "_qm_escalated_at"  # stamped per (task, classification)
ALERT_ID_PREFIX = "quality_monitor_alert_"

Classification = str  # "stuck" | "waiting_for_input_too_long" | "falsely_completed" | "genuinely_failed" | "healthy"


@dataclass
class QualityFinding:
    task_id: str
    classification: Classification
    reason: str
    action: str  # "restarted" | "escalated" | "none"
    detail: Optional[str] = None


def load_final_answer(task_id: str) -> Optional[str]:
    """Same lookup Scheduler._load_final_answer uses — duplicated here (not
    imported from core.py) so this module has no dependency on a live
    Scheduler instance and stays independently unit-testable.

    Found live 2026-09-18: 28eb4899_qm_restart_1's report stored
    final_answer as {"raw_text": "..."} (a structured-output shape some
    model backends produce) rather than a plain string. Concatenating that
    dict into a goal string in _build_continuation_task crashed with
    "unsupported operand type(s) for +: 'dict' and 'str'", silently
    breaking every quality-monitor tick (caught non-fatally by core.py, so
    the scheduler kept running -- but the monitor itself did nothing) for
    hours. Always return a str or None here; never let a raw dict escape
    this function no matter what shape a report happens to use."""
    try:
        report_path = Path(get_memory_subpath("task_reports", f"{task_id}.json"))
        if report_path.exists():
            with open(report_path) as f:
                d = json.load(f)
            answer = d.get("final_answer") or d.get("content")
            if isinstance(answer, str):
                return answer
            if isinstance(answer, dict):
                for key in ("raw_text", "text", "content", "final_answer"):
                    if isinstance(answer.get(key), str):
                        return answer[key]
                return json.dumps(answer)
            if answer is not None:
                return str(answer)
    except Exception:
        pass
    return None


def _extract_done_when(goal: str) -> Optional[str]:
    m = re.search(r"Done when:\s*(.+)", goal or "", re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else None


def default_pr_exists_checker(repo: str, branch: str) -> Optional[bool]:
    """True/False if `gh` can answer definitively; None if the check itself
    couldn't run (gh missing, network down, etc.) — a checker failure is
    NOT the same as "condition is false", never conflate the two."""
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--repo", repo, "--head", branch,
             "--state", "all", "--json", "number"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout or "[]")
        return len(data) > 0
    except Exception:
        return None


def default_file_exists_checker(path: str) -> Optional[bool]:
    try:
        return Path(path).expanduser().is_file()
    except Exception:
        return None


def check_done_when(
    goal: str,
    pr_checker: Callable[[str, str], Optional[bool]] = default_pr_exists_checker,
    file_checker: Callable[[str], Optional[bool]] = default_file_exists_checker,
) -> Optional[bool]:
    """
    Verify a goal's "Done when: ..." clause directly, if it's one of the
    mechanically-checkable shapes we recognize. Returns:
      True  -- condition verified true
      False -- condition verified false (this is the falsely_completed case)
      None  -- no checkable clause found, or the clause isn't a shape we
               recognize, or the checker itself couldn't run. None means
               "don't guess" — never treat None as False.
    """
    clause = _extract_done_when(goal)
    if not clause:
        return None

    pr_m = re.search(r"PR exists on ([\w.-]+/[\w.-]+) from ([\w./-]+?)(?:\s+against|\s*,|\s*$)", clause)
    if pr_m:
        return pr_checker(pr_m.group(1), pr_m.group(2))

    file_m = re.search(r"([./\w-]+\.\w+)\s+(?:exists|is present)", clause)
    if file_m:
        return file_checker(file_m.group(1))

    return None


def classify_task(
    task: Task,
    now: Optional[datetime] = None,
    final_answer_loader: Callable[[str], Optional[str]] = load_final_answer,
    done_when_checker: Callable[[str], Optional[bool]] = check_done_when,
) -> Optional[QualityFinding]:
    """Pure classification — no side effects, no queue mutation. Returns
    None for tasks needing no attention at all (e.g. still-fresh PENDING)."""
    now = now or datetime.now()
    goal = (task.config or {}).get("goal", "") or ""

    if task.status == TaskStatus.RUNNING:
        max_duration = getattr(task.resources, "max_duration_seconds", None) if task.resources else None
        if max_duration and task.started_at:
            elapsed = (now - task.started_at).total_seconds()
            if elapsed > max_duration + STUCK_GRACE_SECONDS:
                return QualityFinding(
                    task.id, "stuck",
                    f"running {elapsed:.0f}s, past max_duration_seconds={max_duration} (+{STUCK_GRACE_SECONDS}s grace)",
                    action="none",  # filled in by apply_action
                )
        return None

    if task.status == TaskStatus.WAITING_FOR_INPUT:
        # Use last update we have -- started_at if set, else created_at.
        since = task.started_at or task.created_at
        if since and (now - since) > timedelta(hours=WAITING_TOO_LONG_HOURS):
            return QualityFinding(
                task.id, "waiting_for_input_too_long",
                f"waiting since {since.isoformat()}, past {WAITING_TOO_LONG_HOURS}h threshold",
                action="none",
            )
        return None

    if task.status == TaskStatus.COMPLETED and task.result and task.result.success:
        verdict = done_when_checker(goal)
        if verdict is False:
            final_answer = final_answer_loader(task.id) or ""
            done_when = _extract_done_when(goal) or ""
            return QualityFinding(
                task.id, "falsely_completed",
                f"self-reported success but Done-when condition is false: {done_when}",
                action="none",
                detail=final_answer,
            )
        return None

    if task.status == TaskStatus.FAILED and not task.can_retry():
        return QualityFinding(
            task.id, "genuinely_failed",
            f"failed, retry_count={task.retry_count} >= max_retries={task.max_retries}: {task.last_error}",
            action="none",
        )

    return None


def _restart_count(task: Task) -> int:
    return int((task.config or {}).get(QM_RESTART_COUNT_KEY, 0))


def _escalation_key(classification: Classification) -> str:
    return f"{QM_ESCALATED_KEY}:{classification}"


def _already_escalated(task: Task, classification: Classification) -> bool:
    """True if this task was already escalated for this classification.
    A terminal finding is a statement of fact -- once a human is notified,
    re-notifying every tick is noise, not signal (the exact failure mode
    that produced the 56-identical-alert storm on sub_28eb4899_952400)."""
    return bool((task.config or {}).get(_escalation_key(classification)))


def _mark_escalated(queue: TaskQueue, task: Task, classification: Classification, now: Optional[datetime] = None) -> None:
    """Stamp the subject task so future passes suppress duplicates. Mutation
    is persisted immediately -- the task is the live queue object."""
    task.config = dict(task.config or {})
    task.config[_escalation_key(classification)] = (now or datetime.now()).isoformat()
    queue.update(task)


def _live_alert_exists(queue: TaskQueue, original_task_id: str, classification: Classification) -> bool:
    """Reactive guard on the alert side: never create a second unresolved
    alert for the same (task, classification) even if the subject marker is
    somehow absent (e.g. alerts pre-existing before this fix deployed)."""
    for t in queue.list_tasks():
        if t.id.startswith(ALERT_ID_PREFIX):
            cfg = t.config or {}
            if (cfg.get("original_task_id") == original_task_id
                    and cfg.get("classification") == classification):
                return True
    return False


def _build_continuation_task(original: Task, finding: QualityFinding) -> Task:
    prior_count = _restart_count(original)
    goal = (original.config or {}).get("goal", "") or ""
    continuation_goal = (
        f"{goal}\n\n"
        f"--- Quality Monitor continuation (restart {prior_count + 1}/{RESTART_CAP}) ---\n"
        f"A prior run of this exact goal (task {original.id}) stopped without meeting "
        f"the Done-when condition above. {finding.reason}\n"
    )
    if finding.detail:
        continuation_goal += f"What the prior run reported doing:\n{finding.detail}\n"
    continuation_goal += (
        "Do not just re-plan from scratch -- pick up from what was already done and "
        "finish the remaining Done-when condition."
    )

    new_config = dict(original.config or {})
    new_config["goal"] = continuation_goal
    new_config[QM_RESTART_COUNT_KEY] = prior_count + 1
    new_config[QM_ORIGIN_KEY] = original.id

    return Task(
        id=f"{original.id}_qm_restart_{prior_count + 1}",
        type=original.type,
        status=TaskStatus.PENDING,
        priority=original.priority or TaskPriority.MEDIUM,
        config=new_config,
        resources=original.resources,
        created_by="quality_monitor",
    )


def _raise_alert(queue: TaskQueue, finding: QualityFinding, now: Optional[datetime] = None) -> bool:
    """Surface via the EXISTING Discord HITL path -- the Discord adapter
    already polls queue.list_tasks(status=WAITING_FOR_INPUT) for any task
    with pending_question set (see app/mcp/adapters/hitl/discord.py) and
    delivers it. No new notification channel needed.

    Returns True if an alert was actually raised, False if a live alert for
    the same (task, classification) already exists (dedupe guard)."""
    if _live_alert_exists(queue, finding.task_id, finding.classification):
        return False
    alert_id = f"{ALERT_ID_PREFIX}{finding.task_id}_{int((now or datetime.now()).timestamp())}"
    question = (
        f"Quality Monitor: task {finding.task_id} classified as "
        f"'{finding.classification}' -- {finding.reason}"
    )
    alert = Task(
        id=alert_id,
        type=TaskType.CUSTOM,
        status=TaskStatus.WAITING_FOR_INPUT,
        priority=TaskPriority.HIGH,
        config={"source": "quality_monitor", "original_task_id": finding.task_id,
                "classification": finding.classification},
        created_by="quality_monitor",
    )
    alert.pending_question = question
    queue.add(alert)
    return True


def apply_action(queue: TaskQueue, task: Task, finding: QualityFinding, now: Optional[datetime] = None) -> QualityFinding:
    """Decide + perform restart vs escalate, per the confirmed design:
    auto-restart ONLY for falsely_completed/stuck cases where the restart
    cap isn't exhausted; everything else (waiting_for_input_too_long,
    genuinely_failed, or cap exhausted) escalates. Never both, never
    neither -- every unhealthy finding gets exactly one action."""
    can_auto_restart = finding.classification in ("falsely_completed", "stuck")
    if can_auto_restart and _restart_count(task) < RESTART_CAP:
        continuation = _build_continuation_task(task, finding)
        queue.add(continuation)
        finding.action = "restarted"
        finding.detail = (finding.detail or "") + f"\n-> continuation task: {continuation.id}"
    else:
        raised = _raise_alert(queue, finding, now=now)
        finding.action = "escalated"
        if raised:
            # One notification per (task, classification). Only stamp when an
            # alert was actually created so a future reprocess after it is
            # resolved can escalate again if the situation recurs.
            _mark_escalated(queue, task, finding.classification, now=now)
    return finding


def run_quality_check(
    queue: TaskQueue,
    now: Optional[datetime] = None,
    final_answer_loader: Callable[[str], Optional[str]] = load_final_answer,
    done_when_checker: Callable[[str], Optional[bool]] = check_done_when,
) -> List[QualityFinding]:
    """Top-level entry point, called periodically from Scheduler._ticker_loop.
    Returns every finding (including a healthy pass logged by the caller as
    'all healthy' when this list is empty) -- never silent.

    final_answer_loader/done_when_checker are threaded through explicitly
    (not relied on as classify_task's own defaults) so tests can inject
    fakes without monkeypatching module globals, which wouldn't affect
    classify_task's already-bound default arguments anyway."""
    now = now or datetime.now()
    findings: List[QualityFinding] = []
    for task in queue.list_tasks():
        if task.created_by == "quality_monitor" or task.id.startswith(ALERT_ID_PREFIX):
            continue  # never watch our own restarts/alerts as if they were subjects
        finding = classify_task(
            task, now=now,
            final_answer_loader=final_answer_loader,
            done_when_checker=done_when_checker,
        )
        if finding is None:
            continue
        if _already_escalated(task, finding.classification):
            continue  # already notified once for this state; don't repeat
        findings.append(apply_action(queue, task, finding, now=now))
    return findings
