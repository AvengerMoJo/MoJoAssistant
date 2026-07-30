"""
Shared provider-error classification — used by both resource_pool.py's
circuit breaker (direct LLM calls) and coding_agent_executor.py's OpenCode
log-tail check (calls MoJoAssistant never makes directly).

Extracted 2026-07-30 after a real incident: zai-coding-plan's GLM-5.1 hit a
5-hour usage cap. Every failure — a genuine multi-hour quota exhaustion and
a one-off connection blip — was treated identically by both callers (a flat
"consecutive_errors" counter with a blind 300s recovery window), so a quota
error that stated its own reset time in plain text
("Your limit will reset at 2026-07-30 15:04:03") got no better treatment
than a transient network hiccup. This module extracts a reusable
classification step so a stated reset time is actually used.

Mirrors and extends AgenticExecutor._FAILURE_TAXONOMY's category list —
that method still exists for its own post-hoc lesson-writing purpose and
is unaffected by this module.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Tuple

# Same categories as AgenticExecutor._FAILURE_TAXONOMY, plus quota_exhausted
# split out from the old catch-all "external_unavailable" bucket — a quota
# error has a knowable reset time, a generic rate-limit/timeout/connection
# failure doesn't, and they need different circuit-breaker treatment.
FAILURE_TAXONOMY = {
    "quota_exhausted": ["usage limit", "quota exceeded", "quota exhausted", "429"],
    "missing_resource": ["not found", "unavailable", "no results", "404", "does not exist"],
    "wrong_tool": ["not supported", "platform", "javascript", "requires browser", "fetch_url"],
    "missing_permission": ["blocked by policy", "permission denied", "not allowed", "forbidden"],
    "ambiguous_goal": ["unclear", "ambiguous", "what do you mean", "clarify", "specify"],
    "external_unavailable": ["rate limit", "timeout", "service down", "503", "connection"],
    "knowledge_gap": ["don't know", "no information", "not enough context", "need more"],
}

# "Your limit will reset at 2026-07-30 15:04:03" (naive local datetime — the
# exact format zai-coding-plan uses; no timezone given, assumed local time
# matching the host, same as OpenCode's own log timestamps for this field).
_RESET_AT_RE = re.compile(
    r"reset(?:s)?\s+at\s+(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})", re.IGNORECASE
)

# "retry after 30s" / "retry-after: 30" style — seconds from now.
_RETRY_AFTER_RE = re.compile(r"retry[-\s]after[:\s]+(\d+)", re.IGNORECASE)


def classify_provider_error(error_message: str) -> Tuple[str, Optional[float]]:
    """
    Classify a provider error message into a taxonomy category, and — for
    quota_exhausted errors that state their own reset time — extract that
    time as a Unix timestamp.

    Returns (category, rate_limited_until). rate_limited_until is None
    unless category == "quota_exhausted" AND a reset time was parseable
    from the message; callers should fall back to their own generic
    circuit-breaker behavior in that case, not assume "no rate limit."
    """
    text = error_message or ""
    lower = text.lower()

    category = "unknown"
    for cat, patterns in FAILURE_TAXONOMY.items():
        if any(p in lower for p in patterns):
            category = cat
            break

    if category != "quota_exhausted":
        return category, None

    m = _RESET_AT_RE.search(text)
    if m:
        try:
            dt = datetime.strptime(m.group(1).replace("T", " "), "%Y-%m-%d %H:%M:%S")
            return category, dt.timestamp()
        except ValueError:
            pass

    m = _RETRY_AFTER_RE.search(text)
    if m:
        import time
        return category, time.time() + float(m.group(1))

    return category, None
