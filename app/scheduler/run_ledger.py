"""Append-only ledger of scheduler runs.

Every attempt to run a task -- any task type, any outcome -- appends one JSON line, so
"did the 04:00 job run, with what, and how did it end?" has an answer that survives the
next run. Before this, a recurring task overwrote its own last result, three job types
left no session file, sessions of failed runs still read "running", and the event store
kept only ~2 days (69% of it heartbeats).

Stdlib-only. One file per month (runs_YYYY-MM.jsonl) so retention is deleting old files.
Writing must never take a task down, but a failed write is reported to the caller (the
scheduler logs it as an error) -- it is not swallowed here.
"""
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

OUTCOMES = (
    "completed",           # the task finished successfully
    "failed",              # failed for good (no retries left)
    "failed_will_retry",   # failed; the scheduler will retry the same run
    "timed_out",           # exceeded its wall-clock limit
    "failed_infra",        # an infrastructure dependency was unreachable
    "waiting_for_input",   # paused for a human answer
    "error",               # unexpected exception in the scheduler/executor
)

ERROR_CLASSES = (
    ("no_resource", ("no resource available", "requirements not satisfiable")),
    ("timeout", ("timed out", "exceeded max duration", "timeouterror", "waiting up to", "time budget exhausted")),
    ("infra_unreachable", ("backend not reachable", "all connection attempts failed", "connecterror", "connection refused")),
    ("iteration_budget", ("iteration budget exhausted",)),
    ("security_gate", ("danger budget",)),
    ("parse_error", ("failed to parse", "not valid json")),
    ("pinned_resource_unavailable", ("pinned resource",)),
)


def classify_error(message: Optional[str]) -> Optional[str]:
    """Coarse, stable error class so failures can be counted and trended."""
    if not message:
        return None
    low = message.lower()
    for name, needles in ERROR_CLASSES:
        if any(n in low for n in needles):
            return name
    return "other"


class RunLedger:
    def __init__(self, directory: Optional[Path] = None):
        if directory is None:
            from app.config.paths import get_memory_subpath
            directory = Path(get_memory_subpath("runs"))
        self._dir = Path(directory)
        self._lock = threading.Lock()

    def _file_for(self, when: datetime) -> Path:
        return self._dir / f"runs_{when:%Y-%m}.jsonl"

    def append(self, entry: Dict[str, Any]) -> None:
        """Append one run record. Raises on I/O failure so the caller can report it."""
        ended = entry.get("ended_at")
        when = datetime.fromisoformat(ended) if ended else datetime.now()
        if entry.get("outcome") not in OUTCOMES:
            raise ValueError(f"run ledger: unknown outcome {entry.get('outcome')!r}, expected one of {OUTCOMES}")
        line = json.dumps(entry, default=str, ensure_ascii=False)
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(self._file_for(when), "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def _files_newest_first(self) -> List[Path]:
        return sorted(self._dir.glob("runs_*.jsonl"), reverse=True) if self._dir.exists() else []

    def iter_entries(self, since: Optional[datetime] = None) -> Iterable[Dict[str, Any]]:
        """Entries, newest monthly file first. A damaged line is skipped so it cannot hide the rest of the history."""
        for path in self._files_newest_first():
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if since and e.get("ended_at") and datetime.fromisoformat(e["ended_at"]) < since:
                        continue
                    yield e

    def recent(self, task_id: Optional[str] = None, limit: int = 50, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Most recent runs first."""
        out = [e for e in self.iter_entries(since) if task_id is None or e.get("task_id") == task_id]
        out.sort(key=lambda e: e.get("ended_at") or "", reverse=True)
        return out[:limit]

    def last_success(self, task_id: str) -> Optional[Dict[str, Any]]:
        return next((e for e in self.recent(task_id, limit=10_000) if e.get("outcome") == "completed"), None)

    def summary(self, since: datetime) -> Dict[str, Dict[str, Any]]:
        """Per task: run counts by outcome, last run, last success."""
        per: Dict[str, Dict[str, Any]] = {}
        for e in sorted(self.iter_entries(since), key=lambda e: e.get("ended_at") or ""):
            s = per.setdefault(e["task_id"], {"runs": 0, "outcomes": {}, "last_run": None, "last_success": None, "last_error": None})
            s["runs"] += 1
            s["outcomes"][e["outcome"]] = s["outcomes"].get(e["outcome"], 0) + 1
            s["last_run"] = e.get("ended_at")
            if e["outcome"] == "completed":
                s["last_success"] = e.get("ended_at")
            elif e.get("error"):
                s["last_error"] = {"at": e.get("ended_at"), "class": e.get("error_class"), "error": e.get("error")}
        return per
