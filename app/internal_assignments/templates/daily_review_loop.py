"""Daily workforce review loop — internal_assignment task template.

Implements design item 4 of
docs/specs/agent_workforce_dashboard_spec.md: the scheduler dispatches
workforce work continuously, and once per day a single HITL checkpoint
pauses for one human review instead of per-task supervision.

Shape (follows the internal_assignment pattern executed by
app/scheduler/handlers/agentic.py — a role-driven think-act loop over
config.goal with config.available_tools):

  - Task definition: build_daily_review_task() → Task(
        type=INTERNAL_ASSIGNMENT, cron_expression="0 18 * * *", ...)
  - HITL stop point + digest raising: raise_digest_to_hitl() wraps
    app/scheduler/hitl_bridge.ask_user — the digest lands in the HITL
    inbox (surfaces in get_context() attention.blocking), the human
    replies via reply_to_task(), the loop's next check_reply() consumes
    it exactly once and the run completes. The scheduler clears stale
    pending_question state between cron cycles (core.py), so each day
    starts from a clean checkpoint.

Create the task once (scheduler MCP `create` or TaskQueue.add); the
cron_expression drives daily recurrence from then on.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.scheduler.hitl_bridge import ask_user
from app.scheduler.models import Task, TaskPriority, TaskStatus, TaskType
from app.scheduler.queue import TaskQueue

CRON_EXPRESSION = "0 18 * * *"

DEFAULT_TASK_ID = "daily-workforce-review"
DEFAULT_ROLE_ID = "daily-reviewer"

AVAILABLE_TOOLS: List[str] = [
    "agent_fleet_summary",
    "agent_sessions_unified",
    "memory_search",
    "external_agent",
]

GOAL_TEMPLATE = """You are the daily workforce reviewer. Produce one digest \
of the agent workforce's day and raise exactly one human checkpoint, then stop.

1. Call agent_fleet_summary() — capture per region/tier group: hosts ok vs
   unreachable, total sessions.
2. Call agent_sessions_unified() — capture per host: session counts by
   origin (mcp / scheduler / human), any notes (degraded hosts, herdr
   unavailable, legacy backends skipped).
3. Compose a SHORT digest (max ~15 lines): what ran, what is still pending,
   any host degraded or unreachable, anything needing a decision. If a tool
   call failed, say so in the digest instead of failing the run.
4. Raise the digest as ONE human checkpoint via the HITL path —
   external_agent(action="ask_user", task_id=..., question=<digest>,
   options=["approve: continue as planned", "investigate: pull details before approving",
   "snooze: skip today"]) — or, when running in-process,
   raise_digest_to_hitl() from this module.
5. STOP. Do not loop, do not re-ask, do not start new workforce work after
   raising the checkpoint. Wait for the human's single reply; a follow-up
   run happens tomorrow via cron.
"""


def build_goal() -> str:
    return GOAL_TEMPLATE


def build_daily_review_task(
    task_id: str = DEFAULT_TASK_ID,
    role_id: str = DEFAULT_ROLE_ID,
    cron_expression: str = CRON_EXPRESSION,
    available_tools: Optional[List[str]] = None,
) -> Task:
    """Build the recurring daily-review internal_assignment Task.

    Register with TaskQueue.add(task) (or the scheduler MCP `create`
    action with the same fields) — cron rescheduling is handled by
    app/scheduler/core.py afterwards.
    """
    return Task(
        id=task_id,
        type=TaskType.INTERNAL_ASSIGNMENT,
        status=TaskStatus.PENDING,
        priority=TaskPriority.MEDIUM,
        cron_expression=cron_expression,
        created_by="system",
        description="Daily workforce digest + single HITL review checkpoint",
        config={
            "role_id": role_id,
            "goal": build_goal(),
            "available_tools": (
                list(available_tools) if available_tools is not None else list(AVAILABLE_TOOLS)
            ),
            "daily_review_loop": True,
        },
    )


def raise_digest_to_hitl(
    queue: TaskQueue,
    task_id: str,
    digest: str,
    options: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Raise the day's digest into the HITL inbox — the loop's stop point.

    Wraps hitl_bridge.ask_user: the task flips to WAITING_FOR_INPUT with
    the digest as its pending question; the human answers once via
    reply_to_task(); a subsequent check_reply() consumes the answer and
    the run completes. Returns ask_user's {"status": "waiting", ...} dict.
    """
    if options is None:
        options = [
            "approve: continue as planned",
            "investigate: pull details before approving",
            "snooze: skip today",
        ]
    return ask_user(queue=queue, task_id=task_id, question=digest, options=options)
