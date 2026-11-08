"""Durable record of what went wrong INSIDE a task run, whether or not the task finished.

A mid-run failure (a provider refusing a call, a resource excluded for the task) used to exist only as a log line
and an iteration_log entry that a retry overwrites -- a task that went on to complete left no trace, so nothing
could learn from it (2026-10-25: a browser tool dumped a page, the context reached ~450k tokens, two providers
answered 400, the retry succeeded and the incident vanished). Each incident is one JSONL row under
~/.memory/state/task_incidents.jsonl: ids, a classified kind, sizes and the last tool -- never prompt content.

Phase 1 of the BRIDLE learning loop (2026-11-08) added the two things that made the log unusable:

  * the provider's own words. `error` kept only the HTTP status line ("400 Bad Request"), so the same
    MiniMax 400 that hit four tasks could not be told apart from any other 400. The body of the failed
    response is now stored in `response_body` (first 500 chars, secrets scrubbed) -- the HTTP client
    (httpx) keeps it on the raised HTTPStatusError, so it is passed through from the LLM call error.
  * `repeated_patterns()`: the same failure seen in several distinct tasks is one pattern, not several
    incidents. Rows are grouped by (resource, kind, normalised signature) and a group that hit at least
    `min_tasks` distinct tasks inside `window_days` is a pattern worth a human's attention.

Nothing here changes routing: no resource is disabled, excluded or re-ranked. This module only records
and reports.
"""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config.paths import get_memory_subpath

CONTEXT_REFUSAL_MARKERS = ("context", "too long", "too many tokens", "maximum", "exceed")

# How much of the provider's response body is kept. A provider's error payload is small; the first
# 500 characters carry the message ("...prompt is too long: 195000 tokens > 163840 maximum...").
RESPONSE_BODY_CHARS = 500

# How much of the normalised provider message goes into a pattern signature.
SIGNATURE_MESSAGE_CHARS = 80


def incidents_path() -> Path:
    return Path(get_memory_subpath("state", "task_incidents.jsonl"))


# --------------------------------------------------------------------------------------
# Secret scrubbing
# --------------------------------------------------------------------------------------
# A provider's error body is copied verbatim from the wire, so it can carry the credential that
# was rejected (an expired key echoed back) or a URL with the key in the query string. Four
# shapes are scrubbed: the Authorization field, api_key(-ish) fields, Bearer tokens and `key=`
# query values. The rules run in this order so a value is removed whole before the field around
# it is rewritten.
_SECRET_RULES: Tuple[Tuple["re.Pattern[str]", str], ...] = (
    # Bearer <token> anywhere (Authorization: Bearer sk-...).
    (re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9._\-+/=]{6,})"), r"\1 [REDACTED]"),
    # Authorization: <value> -- a quoted value, or a bare token.
    (re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"), r"\1[REDACTED]"),
    # api_key / api-key / apikey / x-api-key, as a JSON field or a query value.
    (re.compile(r"(?i)((?:[\"']?(?:x[-_])?api[-_]?key[\"']?)\s*[:=]\s*[\"']?)([^\"'\s,}&]+)"), r"\1[REDACTED]"),
    # key=... query values (?key=abc123&x=1) -- the bare key field is only scrubbed in the
    # query-string form so an ordinary JSON field named "key" keeps its value.
    (re.compile(r"(?i)((?<![\w-])key\s*=\s*)([^\"'\s,}&]+)"), r"\1[REDACTED]"),
)


def scrub_secrets(text: Optional[str]) -> Optional[str]:
    """Remove credentials from a provider's response body. Returns None for an empty body."""
    if not text:
        return None
    out = text
    for pattern, replacement in _SECRET_RULES:
        out = pattern.sub(replacement, out)
    return out


def extract_response_body(exc: BaseException) -> Optional[str]:
    """The body of the failed HTTP response, when the HTTP client kept it.

    httpx raises HTTPStatusError with the response still attached, so the provider's own error
    payload survives the raise. Returns None when the failure had no HTTP response behind it
    (a timeout, a connection error) -- there is no body to record, and none is guessed.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None
    text = getattr(response, "text", None)
    if not isinstance(text, str):
        return None
    if not text.strip():
        return None
    return text


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
                    iteration_log: List[Dict[str, Any]], path: Optional[Path] = None,
                    response_body: Optional[str] = None) -> Dict[str, Any]:
    """Write one incident row and return it.

    `response_body` is the provider's own answer (the JSON error payload, the plain-text refusal).
    It is scrubbed of credentials first and then cut to RESPONSE_BODY_CHARS, so a key that starts
    near the cut is removed rather than half-copied. Rows written before this field existed have
    no `response_body` key at all and still load.
    """
    body = scrub_secrets(response_body)
    row = {"t": time.time(), "task_id": task_id, "role_id": role_id, "resource": resource_id, "iteration": iteration,
           "kind": classify(error, est_input_tokens, context_limit), "error": (error or "")[:300],
           "response_body": body[:RESPONSE_BODY_CHARS] if body else None,
           "est_input_tokens": est_input_tokens, "context_limit": context_limit,
           "largest_message_chars": largest_message_chars, "last_tool": last_tool(iteration_log)}
    p = path or incidents_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


# --------------------------------------------------------------------------------------
# Reading the log
# --------------------------------------------------------------------------------------
def read_rows(path: Optional[Path] = None) -> Tuple[List[Dict[str, Any]], int]:
    """(rows, malformed line count). A half-written last line is normal for an append-only log, so
    it is skipped and counted -- never silently dropped without a number the caller can report."""
    p = path or incidents_path()
    if not p.exists():
        return [], 0
    rows: List[Dict[str, Any]] = []
    malformed = 0
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            malformed += 1
    return rows, malformed


def load_incidents(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every incident row, oldest first. Rows without `response_body` (written before Phase 1)
    load unchanged."""
    rows, _ = read_rows(path)
    return rows


# --------------------------------------------------------------------------------------
# Pattern detection
# --------------------------------------------------------------------------------------
# Identifiers that change between otherwise identical failures are blanked out, so two rows that
# differ only in a request id or a token count land in the same group.
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_PREFIXED_ID_RE = re.compile(
    r"\b(?:sk|pk|api|key|task|req|resp|chat|cmpl|conv|sess|msg|trace|err|error)[-_][A-Za-z0-9_-]{6,}\b",
    re.IGNORECASE,
)
_HEX_ID_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_DIGITS_RE = re.compile(r"\d+")
_WHITESPACE_RE = re.compile(r"\s+")
# An HTTP status code as it appears in the error line: "Client error '400 Bad Request' for url ...".
_STATUS_RE = re.compile(r"\b([1-5]\d{2})\b")
# A status code inside a provider's JSON error payload: {"error": {"code": 400, ...}}.
_BODY_STATUS_RE = re.compile(r"\"(?:code|status|status_code)\"\s*:\s*(\d{3})")


def normalize_message(text: Optional[str]) -> str:
    """Blank out the parts of a provider message that differ between two copies of the same
    failure: digits (token counts, ids made of digits) and identifiers (uuids, hex ids, prefixed
    keys like sk-...)."""
    out = text or ""
    out = _UUID_RE.sub("<id>", out)
    out = _PREFIXED_ID_RE.sub("<id>", out)
    out = _HEX_ID_RE.sub("<id>", out)
    out = _DIGITS_RE.sub("<n>", out)
    return _WHITESPACE_RE.sub(" ", out).strip()


def _row_status(row: Dict[str, Any]) -> str:
    """The HTTP status the incident carried, as a string ('' when there was none)."""
    match = _STATUS_RE.search(str(row.get("error") or ""))
    if match:
        return match.group(1)
    body = row.get("response_body")
    if isinstance(body, str):
        match = _BODY_STATUS_RE.search(body)
        if match:
            return match.group(1)
    return ""


def _provider_message(row: Dict[str, Any]) -> str:
    """What the provider said. New rows carry the response body; rows written before Phase 1 fall
    back to the error line, which is all that was kept then."""
    body = row.get("response_body")
    if isinstance(body, str) and body.strip():
        return body
    return str(row.get("error") or "")


def signature_for(row: Dict[str, Any]) -> str:
    """status + the first SIGNATURE_MESSAGE_CHARS of the normalised provider message."""
    status = _row_status(row)
    message = normalize_message(_provider_message(row))[:SIGNATURE_MESSAGE_CHARS]
    return f"{status}|{message}"


def _row_time(row: Dict[str, Any]) -> Optional[float]:
    value = row.get("t")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def repeated_patterns(min_tasks: int = 2, window_days: int = 14, path: Optional[Path] = None,
                       now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Failure patterns: the same provider failure seen in at least `min_tasks` distinct tasks.

    Rows are grouped by (resource, kind, signature), where the signature is the HTTP status plus
    the first 80 characters of the provider's message with digits and identifiers blanked out. Only
    rows inside the last `window_days` are considered; a row whose timestamp is missing cannot be
    shown to be outside the window, so it is kept.

    Each group reports the number of incidents, the number of distinct tasks, when it was first and
    last seen, a few example task ids and the range of `largest_message_chars` across the group
    (the size of the biggest message that was sent when it happened -- a group that only fails on
    very large messages is a different problem from one that fails on small ones).
    """
    rows, _ = read_rows(path)
    return patterns_from_rows(rows, min_tasks=min_tasks, window_days=window_days, now=now)


def patterns_from_rows(rows: List[Dict[str, Any]], min_tasks: int = 2, window_days: int = 14,
                        now: Optional[float] = None) -> List[Dict[str, Any]]:
    """`repeated_patterns` over rows the caller has already read."""
    now = time.time() if now is None else now
    cutoff = now - (window_days * 86400.0)

    groups: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for row in rows:
        ts = _row_time(row)
        if ts is not None and ts < cutoff:
            continue
        resource = str(row.get("resource") or row.get("resource_id") or "")
        kind = str(row.get("kind") or "")
        signature = signature_for(row)
        key = (resource, kind, signature)
        group = groups.get(key)
        if group is None:
            group = {
                "resource_id": resource,
                "kind": kind,
                "signature": signature,
                "status": _row_status(row),
                "message": signature.split("|", 1)[1] if "|" in signature else signature,
                "count": 0,
                "task_ids": [],
                "first_seen_ts": ts,
                "last_seen_ts": ts,
                "largest_message_chars_values": [],
            }
            groups[key] = group
        group["count"] += 1
        task_id = str(row.get("task_id") or "")
        if task_id and task_id not in group["task_ids"]:
            group["task_ids"].append(task_id)
        if ts is not None:
            if group["first_seen_ts"] is None or ts < group["first_seen_ts"]:
                group["first_seen_ts"] = ts
            if group["last_seen_ts"] is None or ts > group["last_seen_ts"]:
                group["last_seen_ts"] = ts
        size = row.get("largest_message_chars")
        if isinstance(size, int):
            group["largest_message_chars_values"].append(size)

    patterns: List[Dict[str, Any]] = []
    for group in groups.values():
        task_count = len(group["task_ids"])
        if task_count < min_tasks:
            continue
        sizes = group["largest_message_chars_values"]
        patterns.append({
            "resource_id": group["resource_id"],
            "kind": group["kind"],
            "signature": group["signature"],
            "status": group["status"],
            "message": group["message"],
            "count": group["count"],
            "task_count": task_count,
            "first_seen": _iso(group["first_seen_ts"]),
            "last_seen": _iso(group["last_seen_ts"]),
            "example_task_ids": group["task_ids"][:5],
            "largest_message_chars_min": min(sizes) if sizes else None,
            "largest_message_chars_max": max(sizes) if sizes else None,
        })

    patterns.sort(key=lambda p: (-p["task_count"], -p["count"], p["resource_id"], p["kind"], p["signature"]))
    return patterns


def pattern_key(pattern: Dict[str, Any]) -> str:
    """A stable key for one pattern -- the same pattern must keep the same key across runs so the
    daily step can tell a new pattern from one it has already reported."""
    return f"{pattern.get('resource_id', '')}|{pattern.get('kind', '')}|{pattern.get('signature', '')}"
