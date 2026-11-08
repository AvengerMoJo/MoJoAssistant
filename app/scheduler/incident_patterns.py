"""Daily scan of the incident log for repeated provider failures -- observation only.

Phase 1 of the BRIDLE learning loop (2026-11-08). `task_incidents.py` records what went wrong
inside a task run; until now nothing read that log, so a provider that answered 400 to four
different tasks was four anonymous lines in a file. This module is the reader:

  1. group the incidents into patterns (`task_incidents.repeated_patterns`)
  2. write them to ~/.memory/state/incident_patterns.json
  3. tell the owner ONCE -- only when a pattern is new or its count crossed a threshold, and at
     most one notification per day

What this module deliberately does NOT do: it never disables a resource, never excludes one and
never changes the ranking. It reads a log and writes a report; what the owner does with the report
is a decision for a human (or for a later phase of the loop, once the signal is proven).

When is a pattern reported?
---------------------------
A pattern is reported when it is **new** (the owner has never been told about it) or when its
incident count **crossed a threshold** (it entered a new band `count // notify_threshold`; band 0
is "below the threshold", band 1 is "the threshold was crossed", band 2 is "twice the threshold").
A new pattern is reported as soon as it is seen, even below the threshold -- the owner should hear
about a fresh failure pattern once, not only once it has grown.

The state file carries what has already been reported (`notified`), so the daily step can tell
"a pattern I have never told the owner about" from "the same pattern, one more time".
`notified_count` is the count the owner was last told about (the number the next threshold
comparison uses); `last_count` is the latest observation.

At most one notification leaves per day. A pattern that crossed while the day's notification was
already used stays pending -- it is reported the next day. A notification is delayed, never
dropped, and never sent twice for the same crossing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.config.paths import get_memory_subpath
from app.scheduler.task_incidents import (
    pattern_key,
    patterns_from_rows,
    read_rows,
)

DEFAULT_MIN_TASKS = 2
DEFAULT_WINDOW_DAYS = 14
DEFAULT_NOTIFY_THRESHOLD = 3
STATE_FILE_NAME = "incident_patterns.json"

NotifyFn = Callable[[str, str], Awaitable[None]]


def patterns_state_path() -> Path:
    return Path(get_memory_subpath("state", STATE_FILE_NAME))


def load_state(path: Optional[Path] = None) -> Dict[str, Any]:
    """The previous state, or an empty state when there is none. A state file that cannot be
    parsed is an error the caller must see, not a reason to start from zero and re-notify."""
    p = path or patterns_state_path()
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{p} is not a JSON object")
    return data


def write_state(state: Dict[str, Any], path: Optional[Path] = None) -> Path:
    """Write the state file and read it back: a report that cannot be parsed is worthless, and a
    silent half-written file would hide the patterns it claims to hold."""
    p = path or patterns_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    readback = json.loads(p.read_text(encoding="utf-8"))
    if readback.get("pattern_count") != state.get("pattern_count"):
        raise ValueError(f"incident pattern state did not survive the write-back: {p}")
    return p


def threshold_band(count: int, threshold: int) -> int:
    """Which threshold band a count is in. Band 0 is below the threshold, band 1 is the threshold
    itself, band 2 is twice the threshold."""
    if threshold <= 0:
        return count
    return count // threshold


def is_reportable(pattern: Dict[str, Any], notified: Dict[str, Any], threshold: int) -> bool:
    """True when the owner has to hear about this pattern: it is new, or it grew into a threshold
    band they have not been told about yet."""
    entry = notified.get(pattern_key(pattern))
    if entry is None:
        return True  # never reported -> new
    notified_count = int(entry.get("notified_count") or 0)
    return (threshold_band(int(pattern.get("count") or 0), threshold)
            > threshold_band(notified_count, threshold))


def format_pattern_line(pattern: Dict[str, Any]) -> str:
    size_min = pattern.get("largest_message_chars_min")
    size_max = pattern.get("largest_message_chars_max")
    if size_min is None or size_max is None:
        size = "message size unknown"
    elif size_min == size_max:
        size = f"largest message {size_max} chars"
    else:
        size = f"largest message {size_min}-{size_max} chars"
    tasks = ", ".join(pattern.get("example_task_ids") or [])
    return (f"  {pattern.get('resource_id')} / {pattern.get('kind')} / status {pattern.get('status') or '?'}"
            f" -- {pattern.get('count')} incident(s) in {pattern.get('task_count')} task(s)"
            f" [{pattern.get('first_seen')} .. {pattern.get('last_seen')}]"
            f" ({size})"
            + (f"\n    tasks: {tasks}" if tasks else "")
            + (f"\n    provider said: {pattern.get('message')}" if pattern.get("message") else ""))


def format_notification(patterns: List[Dict[str, Any]]) -> Dict[str, str]:
    """The one notification the daily step may send."""
    lines = [format_pattern_line(p) for p in patterns]
    body = ("Repeated provider failure pattern(s) across tasks:\n" + "\n".join(lines)
            + "\n\nObservation only -- no resource was disabled, excluded or re-ranked."
            + "\nFull report: ~/.memory/state/incident_patterns.json")
    return {"title": f"Provider incident pattern ({len(patterns)})", "body": body}


async def scan_patterns(
    *,
    incidents_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
    min_tasks: int = DEFAULT_MIN_TASKS,
    window_days: int = DEFAULT_WINDOW_DAYS,
    notify_threshold: int = DEFAULT_NOTIFY_THRESHOLD,
    now: Optional[datetime] = None,
    notify: Optional[NotifyFn] = None,
) -> Dict[str, Any]:
    """Read the incident log, write the pattern report and (maybe) send one notification.

    Returns a summary dict. `notified` is True only when a notification was actually sent;
    `pending` lists the patterns that were ready to be reported but were not (the daily cap was
    already used, or no notifier was supplied), so the caller can see that they are waiting.
    """
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()

    rows, malformed = read_rows(incidents_path)
    patterns = patterns_from_rows(rows, min_tasks=min_tasks, window_days=window_days, now=now.timestamp())

    state_path = state_path or patterns_state_path()
    previous = load_state(state_path)
    # Only patterns that were actually reported live in `notified`. A pattern that was seen but
    # never reported (the daily cap was used) stays "new" and is reported the next day.
    notified: Dict[str, Any] = {k: dict(v) for k, v in (previous.get("notified") or {}).items()}

    reportable = [p for p in patterns if is_reportable(p, notified, notify_threshold)]

    state: Dict[str, Any] = {
        "generated_at": now.isoformat(),
        "min_tasks": min_tasks,
        "window_days": window_days,
        "notify_threshold": notify_threshold,
        "pattern_count": len(patterns),
        "patterns": patterns,
        "notified": notified,
        "last_notification_date": previous.get("last_notification_date"),
        "last_notification_at": previous.get("last_notification_at"),
        "malformed_lines": malformed,
    }
    # The report is written BEFORE the notification: if sending fails, the patterns are still on
    # disk and the next run can report them.
    write_state(state, state_path)

    already_notified_today = previous.get("last_notification_date") == today
    notification = format_notification(reportable) if reportable else None
    sent = False

    if notification and not already_notified_today and notify is not None:
        await notify(notification["title"], notification["body"])
        sent = True
        for pattern in reportable:
            entry = notified.setdefault(pattern_key(pattern), {"notified_count": 0})
            entry["notified_count"] = int(pattern.get("count") or 0)
            entry["notified_at"] = now.isoformat()
            entry["last_count"] = int(pattern.get("count") or 0)
            entry["task_count"] = pattern.get("task_count")
            entry["last_seen"] = pattern.get("last_seen")
        state["notified"] = notified
        state["last_notification_date"] = today
        state["last_notification_at"] = now.isoformat()
        write_state(state, state_path)
    elif reportable:
        # Keep the latest observation of a pattern that was not reported (yet) -- the state file
        # shows what the log says even when the owner has not been told about it.
        for pattern in reportable:
            entry = notified.setdefault(pattern_key(pattern), {"notified_count": 0})
            entry["last_count"] = int(pattern.get("count") or 0)
            entry["task_count"] = pattern.get("task_count")
            entry["last_seen"] = pattern.get("last_seen")
        state["notified"] = notified
        write_state(state, state_path)

    pending = [] if sent else [pattern_key(p) for p in reportable]
    return {
        "pattern_count": len(patterns),
        "patterns": patterns,
        "reportable": [pattern_key(p) for p in reportable],
        "notified": sent,
        "pending": pending,
        "notification": notification,
        "daily_cap_reached": bool(reportable) and already_notified_today,
        "malformed_lines": malformed,
        "state_path": str(state_path),
        "min_tasks": min_tasks,
        "window_days": window_days,
        "notify_threshold": notify_threshold,
    }
