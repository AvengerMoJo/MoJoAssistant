"""
Google Calendar bridge for agentic tasks.

Exposes two async functions that wrap the `gws` CLI, mirroring the same
approach used by the scheduler's executor.py for calendar event creation.

  calendar_list_events(start_date, end_date, calendar_id, max_results)
      → list events in a date range

  calendar_create_event(title, details, start_at, end_at, calendar_id, timezone)
      → create an event (policy-gated: ops scope only for agent writes)

Both functions return a plain dict: {"success": True/False, "data": ..., "error": ...}
Auth errors surface clearly so the caller can ask the user to re-authenticate.
"""
# [mojo-integration]

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, Optional


async def _run_gws(*args: str) -> Dict[str, Any]:
    """Run a gws command and return parsed JSON output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gws", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        stdout_text = stdout.decode("utf-8", errors="ignore").strip()
        stderr_text = stderr.decode("utf-8", errors="ignore").strip()

        if proc.returncode != 0:
            # Try to parse error JSON from gws
            try:
                err = json.loads(stdout_text)
                msg = err.get("error", {}).get("message", stdout_text or stderr_text)
            except Exception:
                msg = stderr_text or stdout_text or f"exit code {proc.returncode}"
            return {"success": False, "error": msg}

        if not stdout_text:
            return {"success": True, "data": {}}

        try:
            return {"success": True, "data": json.loads(stdout_text)}
        except Exception:
            return {"success": True, "data": {"raw": stdout_text}}

    except asyncio.TimeoutError:
        return {"success": False, "error": "gws command timed out after 30s"}
    except FileNotFoundError:
        return {"success": False, "error": "gws CLI not found — ensure it is installed and on PATH"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _to_rfc3339(date_str: str) -> str:
    """
    Accept ISO date ('2026-04-02') or datetime ('2026-04-02T09:00:00')
    and return a full RFC3339 string with UTC offset for the gws API.
    """
    try:
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str)
        else:
            dt = datetime.fromisoformat(date_str + "T00:00:00")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt.isoformat()
    except Exception:
        return date_str  # pass through and let gws report the error


async def calendar_list_events(
    start_date: str,
    end_date: str,
    calendar_id: str = "primary",
    max_results: int = 20,
) -> Dict[str, Any]:
    """
    List events from Google Calendar between start_date and end_date.

    Parameters
    ----------
    start_date  : ISO date or datetime, e.g. "2026-04-02" or "2026-04-02T00:00:00"
    end_date    : ISO date or datetime, e.g. "2026-04-09"
    calendar_id : Calendar ID (default "primary")
    max_results : Max number of events to return (default 20)

    Returns
    -------
    {"success": True, "events": [...], "count": N}
    {"success": False, "error": "..."}
    """
    params = {
        "calendarId": calendar_id,
        "timeMin": _to_rfc3339(start_date),
        "timeMax": _to_rfc3339(end_date),
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": max_results,
    }
    result = await _run_gws(
        "calendar", "events", "list",
        "--params", json.dumps(params),
        "--format", "json",
    )
    if not result["success"]:
        return result

    data = result.get("data", {})
    events = data.get("items", [])
    # Trim to essential fields for LLM consumption
    slim = []
    for e in events:
        start = e.get("start", {})
        end = e.get("end", {})
        slim.append({
            "id": e.get("id"),
            "summary": e.get("summary", "(no title)"),
            "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"),
            "location": e.get("location"),
            "description": e.get("description"),
            "status": e.get("status"),
        })
    return {"success": True, "events": slim, "count": len(slim)}


async def calendar_create_event(
    title: str,
    start_at: str,
    end_at: Optional[str] = None,
    details: str = "",
    calendar_id: str = "primary",
    timezone: str = "Asia/Taipei",
    duration_minutes: int = 30,
) -> Dict[str, Any]:
    """
    Create a Google Calendar event.

    Parameters
    ----------
    title            : Event title
    start_at         : ISO datetime for event start
    end_at           : ISO datetime for event end (optional, uses duration_minutes if absent)
    details          : Event description/notes
    calendar_id      : Calendar to write to (default "primary")
    timezone         : Timezone string (default "Asia/Taipei")
    duration_minutes : Duration if end_at not provided (default 30)

    Returns
    -------
    {"success": True, "event_id": "...", "html_link": "..."}
    {"success": False, "error": "..."}
    """
    start_dt = datetime.fromisoformat(start_at)
    if end_at:
        end_dt = datetime.fromisoformat(end_at)
    else:
        end_dt = start_dt + timedelta(minutes=duration_minutes)

    payload = {
        "summary": title,
        "description": details,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
        "end":   {"dateTime": end_dt.isoformat(),   "timeZone": timezone},
    }
    params = {"calendarId": calendar_id}

    result = await _run_gws(
        "calendar", "events", "insert",
        "--params", json.dumps(params),
        "--json",   json.dumps(payload),
        "--format", "json",
    )
    if not result["success"]:
        return result

    data = result.get("data", {})
    return {
        "success": True,
        "event_id": data.get("id"),
        "html_link": data.get("htmlLink"),
        "summary": data.get("summary"),
        "start": data.get("start", {}).get("dateTime"),
        "end":   data.get("end", {}).get("dateTime"),
    }
