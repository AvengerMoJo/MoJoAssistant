"""Durable record of what went wrong INSIDE a task run, whether or not the task finished.

A mid-run failure (a provider refusing a call, a resource excluded for the task) used to exist only as a log line
and an iteration_log entry that a retry overwrites -- a task that went on to complete left no trace, so nothing
could learn from it (2026-10-25: a browser tool dumped a page, the context reached ~450k tokens, two providers
answered 400, the retry succeeded and the incident vanished). Each incident is one JSONL row under
~/.memory/state/task_incidents.jsonl: ids, a classified kind, sizes and the last tool -- never prompt content.
The weekly review and the owner of the routine read it; classification is plain code, not a guess.
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.paths import get_memory_subpath

CONTEXT_REFUSAL_MARKERS = ("context", "too long", "too many tokens", "maximum", "exceed")


def incidents_path() -> Path:
    return Path(get_memory_subpath("state", "task_incidents.jsonl"))


def classify(error: str, est_input_tokens: Optional[int], context_limit: Optional[int]) -> str:
    """context_overflow when the request was larger than the model's window (the provider's own 400 text rarely
    says so), rate_limit / auth / provider_4xx / provider_5xx / timeout otherwise, else unknown."""
    e = (error or "").lower()
    if est_input_tokens and context_limit and est_input_tokens > context_limit:
        return "context_overflow"
    if "429" in e or "rate" in e and "limit" in e:
        return "rate_limit"
    if "401" in e or "403" in e:
        return "auth"
    if "timeout" in e or "timed out" in e:
        return "timeout"
    if any(f" {c} " in f" {e} " or f"'{c} " in e for c in ("500", "502", "503", "504")):
        return "provider_5xx"
    if "400" in e and any(m in e for m in CONTEXT_REFUSAL_MARKERS):
        return "context_overflow"
    if "400" in e or "422" in e:
        return "provider_4xx"
    return "unknown"


def last_tool(iteration_log: List[Dict[str, Any]]) -> Optional[str]:
    for entry in reversed(iteration_log):
        if entry.get("tool_calls"):
            return entry["tool_calls"][-1]
    return None


def record_incident(task_id: str, role_id: Optional[str], resource_id: str, error: str, iteration: int,
                    est_input_tokens: Optional[int], context_limit: Optional[int], largest_message_chars: Optional[int],
                    iteration_log: List[Dict[str, Any]], path: Optional[Path] = None) -> Dict[str, Any]:
    row = {"t": time.time(), "task_id": task_id, "role_id": role_id, "resource": resource_id, "iteration": iteration,
           "kind": classify(error, est_input_tokens, context_limit), "error": (error or "")[:300],
           "est_input_tokens": est_input_tokens, "context_limit": context_limit,
           "largest_message_chars": largest_message_chars, "last_tool": last_tool(iteration_log)}
    p = path or incidents_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row
