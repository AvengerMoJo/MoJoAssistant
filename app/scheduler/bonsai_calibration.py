"""Bonsai calibration store: what a kind of task actually used, and why it ended.

Per (role_id, task_type, goal_category) we keep each finished run's actual steps and hours and the
reason it ended.  The next run's budget is suggested from that history (p75 + 20%), so a budget is
data, not a guess.  Design: memory note "Bonsai Architecture" (gas and brake).

End reasons (the exhaustion taxonomy):
  goal_achieved   the work finished
  budget          ran out of steps or hours while working     -> budget too low or prompt too slow
  tool_error      server died / unanswerable prompts / no PR  -> missing capability or credential
  model_confusion nudges did not move it                      -> wrong model tier
  detection_bug   claimed done but the evidence is missing    -> completion signal
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config.paths import get_memory_path

REASONS = ("goal_achieved", "budget", "tool_error", "model_confusion", "detection_bug")
MIN_SAMPLES = 3
BUFFER = 1.2


def _path() -> Path:
    return Path(get_memory_path()) / "state" / "bonsai_calibration.json"


def _load() -> Dict[str, List[Dict[str, Any]]]:
    p = _path()
    return json.loads(p.read_text()) if p.exists() else {}


def key(role_id: str, task_type: str, category: str) -> str:
    return f"{role_id}|{task_type}|{category or 'general'}"


def record(role_id: str, task_type: str, category: str, *, steps: int, hours: float, reason: str, run_id: str) -> None:
    if reason not in REASONS:
        raise ValueError(f"unknown end reason {reason!r}; expected one of {REASONS}")
    data = _load()
    rows = data.setdefault(key(role_id, task_type, category), [])
    if any(r["run_id"] == run_id for r in rows):
        return  # one row per run, even if recorded twice
    rows.append({"run_id": run_id, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "steps": int(steps), "hours": round(float(hours), 2), "reason": reason})
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(p)
    json.loads(p.read_text())  # read back


def _p75(values: List[float]) -> float:
    v = sorted(values)
    return v[min(len(v) - 1, math.ceil(0.75 * len(v)) - 1)]


def suggest(role_id: str, task_type: str, category: str) -> Optional[Dict[str, Any]]:
    """Budget from history, or None when there are too few finished runs to say anything."""
    rows = [r for r in _load().get(key(role_id, task_type, category), []) if r["reason"] == "goal_achieved"]
    if len(rows) < MIN_SAMPLES:
        return None
    return {"max_steps": math.ceil(_p75([r["steps"] for r in rows]) * BUFFER),
            "max_hours": round(_p75([r["hours"] for r in rows]) * BUFFER, 1), "samples": len(rows)}


def summary(role_id: str, task_type: str, category: str) -> Dict[str, Any]:
    rows = _load().get(key(role_id, task_type, category), [])
    by: Dict[str, int] = {}
    for r in rows:
        by[r["reason"]] = by.get(r["reason"], 0) + 1
    return {"runs": len(rows), "by_reason": by, "suggestion": suggest(role_id, task_type, category)}
