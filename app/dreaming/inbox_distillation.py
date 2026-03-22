"""
Inbox Distillation — serialize resolved HITL interactions into dreaming input.

Reads the previous day's EventLog, pairs task_waiting_for_input +
task_completed/task_failed events by task_id, serializes them as readable
text, and feeds the result through the DreamingPipeline.

conversation_id: "inbox/inbox_YYYY-MM-DD"
Storage:         ~/.memory/dreams/inbox/inbox_YYYY-MM-DD/
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.dreaming.pipeline import DreamingPipeline
    from app.mcp.adapters.event_log import EventLog

logger = logging.getLogger(__name__)

# Minimum pairs to bother running the pipeline
MIN_PAIRS = 1


def build_inbox_text(target_date: date, event_log: "EventLog") -> Optional[str]:
    """
    Collect resolved HITL interactions for target_date and serialize to text.

    Returns None if no pairs found.
    """
    # Fetch the full day with data payloads
    day_start = datetime.combine(target_date, datetime.min.time()).isoformat()
    day_end = datetime.combine(target_date + timedelta(days=1), datetime.min.time()).isoformat()

    all_events = event_log.get_recent(
        since=day_start,
        limit=2000,
        include_data=True,
    )
    # Keep only events within the target day
    day_events = [
        e for e in all_events
        if day_start <= e.get("timestamp", "") < day_end
    ]

    # Index waiting events by task_id
    waiting: dict[str, dict] = {}
    completed: dict[str, dict] = {}

    for e in day_events:
        etype = e.get("event_type", "")
        data = e.get("data") or {}
        task_id = data.get("task_id") or e.get("id")
        if not task_id:
            continue
        if etype == "task_waiting_for_input":
            waiting[task_id] = e
        elif etype in ("task_completed", "task_failed"):
            completed[task_id] = e

    # Build pairs: only tasks that both asked AND resolved
    pairs = [
        (waiting[tid], completed[tid])
        for tid in waiting
        if tid in completed
    ]

    if len(pairs) < MIN_PAIRS:
        return None

    lines = [
        f"=== Inbox Distillation: {target_date.isoformat()} ===",
        f"Resolved interactions: {len(pairs)}",
        "",
    ]

    for w_event, c_event in pairs:
        w_data = w_event.get("data") or {}
        c_data = c_event.get("data") or {}
        task_id = w_data.get("task_id", "unknown")
        role = w_data.get("created_by") or w_data.get("agent_id") or "unknown"
        question = w_data.get("question") or w_data.get("pending_question") or "(no question text)"
        reply = w_data.get("user_reply") or c_data.get("user_reply") or "(no reply recorded)"
        outcome = c_event.get("event_type", "unknown")
        completed_at = c_event.get("timestamp", "")

        lines += [
            f"--- Interaction: {task_id} ---",
            f"Role: {role}",
            f"Asked: {question}",
            f"Reply: {reply}",
            f"Outcome: {outcome}",
            f"Completed: {completed_at}",
            "",
        ]

    return "\n".join(lines)


async def run_inbox_distillation(
    target_date: date,
    event_log: "EventLog",
    pipeline: "DreamingPipeline",
    quality_level: str = "basic",
) -> dict:
    """
    Build inbox text and feed it through the dreaming pipeline.

    Returns the pipeline result dict, or a skip/error dict.
    """
    text = build_inbox_text(target_date, event_log)
    if text is None:
        return {
            "status": "skipped",
            "reason": "no_resolved_interactions",
            "date": target_date.isoformat(),
        }

    conversation_id = f"inbox/inbox_{target_date.isoformat()}"
    logger.info(f"InboxDistillation: running pipeline for {conversation_id}")

    result = await pipeline.process_conversation(
        conversation_id=conversation_id,
        conversation_text=text,
        metadata={
            "source": "inbox_distillation",
            "date": target_date.isoformat(),
            "quality_level": quality_level,
        },
    )
    return result
