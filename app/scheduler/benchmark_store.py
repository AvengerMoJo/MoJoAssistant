"""
BenchmarkStore — continuous execution tracking and model auto-tuning.

Every completed production task writes a lightweight record to
~/.memory/benchmarks/execution_log.jsonl. When the scheduler is idle,
it re-runs recent completed tasks with alternative free resources to
build a cross-model comparison dataset.

An LLM-as-judge step (using the fastest available free model) scores
answer quality when both the original and re-run produce a final answer,
giving a signal beyond success/speed alone.

AutoTuner reads the accumulated log and rewrites priority weights in
~/.memory/config/resource_pool.json so the best-performing model for
each role naturally floats to the top.

Layout:
  ~/.memory/benchmarks/execution_log.jsonl  — append-only record of runs
  ~/.memory/benchmarks/tuning_report.json   — latest AutoTuner output
"""
# [mojo-integration]

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import statistics
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _benchmark_dir() -> Path:
    from app.config.paths import get_memory_subpath
    p = Path(get_memory_subpath("benchmarks"))
    p.mkdir(parents=True, exist_ok=True)
    return p

def _log_path() -> Path:
    return _benchmark_dir() / "execution_log.jsonl"

def _report_path() -> Path:
    return _benchmark_dir() / "tuning_report.json"

def _personal_resource_pool_path() -> Path:
    from app.config.paths import get_memory_subpath
    return Path(get_memory_subpath("config", "resource_pool.json"))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ExecutionRecord:
    ts: str                          # ISO timestamp
    task_id: str
    goal_hash: str                   # sha256(goal)[:16] — grouping key
    goal_preview: str                # first 80 chars of goal
    role_id: Optional[str]
    resource_id: str
    model: str
    success: bool
    iterations: int
    duration_s: float
    final_answer_len: int            # 0 if failed
    final_answer_hash: str           # sha256(answer)[:16], "" if failed
    is_rerun: bool = False
    original_task_id: Optional[str] = None
    judge_score: Optional[float] = None   # 1-5, None if not judged
    judge_winner: Optional[str] = None    # "original" | "rerun" | "tie" | None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ExecutionRecord":
        return ExecutionRecord(**{k: d.get(k) for k in ExecutionRecord.__dataclass_fields__})


@dataclass
class ResourceStats:
    resource_id: str
    model: str
    n_runs: int
    success_rate: float
    median_iterations: float
    median_duration_s: float
    judge_win_rate: float            # fraction of judged runs where this resource won
    composite_score: float           # higher = better


# ---------------------------------------------------------------------------
# BenchmarkStore
# ---------------------------------------------------------------------------

class BenchmarkStore:
    """
    Thin wrapper around the JSONL execution log.

    Designed to be instantiated once and kept alive in the scheduler.
    All writes are append-only; reads scan the full log (it's small).
    """

    # How many days back we look for rerun candidates
    RERUN_LOOKBACK_DAYS: int = 7
    # Minimum runs per resource before AutoTuner considers updating priorities
    MIN_SAMPLES_FOR_TUNING: int = 5
    # Maximum number of rerun shadow tasks queued per hour (throttle)
    MAX_RERUNS_PER_HOUR: int = 3
    # Judge prompt max answer length to avoid flooding context
    JUDGE_MAX_ANSWER_LEN: int = 1000

    def __init__(self):
        self._log_path = _log_path()
        self._recent_reruns: List[float] = []  # timestamps of recent rerun dispatches

    # ------------------------------------------------------------------ #
    # Recording
    # ------------------------------------------------------------------ #

    def record_execution(self, task, result) -> None:
        """
        Called by core.py after a task succeeds or fails.
        Extracts metrics from the Task + TaskResult and appends to the log.
        """
        try:
            config = task.config or {}
            # Don't record benchmark reruns of reruns (no recursion)
            is_rerun = bool(config.get("is_benchmark_rerun"))
            goal = config.get("goal", "")
            final_answer = (result.metrics or {}).get("final_answer", "") or ""

            rec = ExecutionRecord(
                ts=datetime.utcnow().isoformat(),
                task_id=task.id,
                goal_hash=_hash(goal),
                goal_preview=goal[:80].replace("\n", " "),
                role_id=config.get("role_id"),
                resource_id=_extract_resource_id(result),
                model=_extract_model(result),
                success=result.success,
                iterations=_extract_iterations(result),
                duration_s=_extract_duration(result),
                final_answer_len=len(final_answer),
                final_answer_hash=_hash(final_answer) if final_answer else "",
                is_rerun=is_rerun,
                original_task_id=config.get("benchmark_original_task_id"),
            )
            self._append(rec)
        except Exception as e:
            logger.warning(f"BenchmarkStore: failed to record execution for {task.id}: {e}")

    def record_judge_result(self, task_id: str, score: float, winner: str) -> None:
        """Update the most recent record for task_id with judge output."""
        try:
            lines = self._log_path.read_text().splitlines() if self._log_path.exists() else []
            updated = []
            found = False
            for line in reversed(lines):
                if not found:
                    try:
                        d = json.loads(line)
                        if d.get("task_id") == task_id:
                            d["judge_score"] = score
                            d["judge_winner"] = winner
                            updated.append(json.dumps(d))
                            found = True
                            continue
                    except Exception:
                        pass
                updated.append(line)
            if found:
                self._log_path.write_text("\n".join(reversed(updated)) + "\n")
        except Exception as e:
            logger.warning(f"BenchmarkStore: failed to update judge result for {task_id}: {e}")

    # ------------------------------------------------------------------ #
    # Rerun candidates
    # ------------------------------------------------------------------ #

    def get_rerun_candidate(self) -> Optional[Dict[str, Any]]:
        """
        Return the config for a shadow rerun task, or None if:
          - rate limit exceeded
          - no suitable candidate found
          - all free resources have already been tested for recent goals

        The returned dict is ready to use as task.config with 'pinned_resource'
        and 'is_benchmark_rerun' already set.
        """
        # Rate limit
        now = time.time()
        self._recent_reruns = [t for t in self._recent_reruns if now - t < 3600]
        if len(self._recent_reruns) >= self.MAX_RERUNS_PER_HOUR:
            return None

        records = self._load_recent(days=self.RERUN_LOOKBACK_DAYS)
        if not records:
            return None

        # Load free resource IDs from the live pool
        free_resources = _get_free_resource_ids()
        if len(free_resources) < 2:
            return None

        # Group production runs by (goal_hash, role_id)
        groups: Dict[Tuple[str, Optional[str]], List[ExecutionRecord]] = {}
        for r in records:
            if r.is_rerun:
                continue
            if not r.success:
                continue
            key = (r.goal_hash, r.role_id)
            groups.setdefault(key, []).append(r)

        # For each group, find resources not yet tested
        for (goal_hash, role_id), prod_runs in groups.items():
            tested = {r.resource_id for r in records
                      if r.goal_hash == goal_hash and r.role_id == role_id}
            untested = [rid for rid in free_resources if rid not in tested]
            if not untested:
                continue

            # Pick the first production run as template and next untested resource
            template = prod_runs[0]
            next_resource = untested[0]

            # Reconstruct a minimal task config from the record
            # (full config is not stored — we only have goal + role + available_tools)
            self._recent_reruns.append(now)
            return {
                "goal": _recover_goal_from_log(goal_hash, records) or template.goal_preview,
                "role_id": role_id,
                "pinned_resource": next_resource,
                "is_benchmark_rerun": True,
                "benchmark_original_task_id": template.task_id,
                "benchmark_goal_hash": goal_hash,
                "max_iterations": 15,  # capped — benchmarks shouldn't run forever
            }

        return None

    # ------------------------------------------------------------------ #
    # Analysis
    # ------------------------------------------------------------------ #

    def analyze(self, min_samples: int = MIN_SAMPLES_FOR_TUNING) -> List[ResourceStats]:
        """
        Compute per-resource stats across all runs in the log.
        Only resources with >= min_samples total runs are included.
        """
        records = self._load_recent(days=90)
        by_resource: Dict[str, List[ExecutionRecord]] = {}
        for r in records:
            by_resource.setdefault(r.resource_id, []).append(r)

        stats = []
        for rid, runs in by_resource.items():
            if len(runs) < min_samples:
                continue
            successes = [r for r in runs if r.success]
            success_rate = len(successes) / len(runs)
            iters = [r.iterations for r in successes] or [0]
            durs = [r.duration_s for r in successes] or [0]
            judge_wins = sum(
                1 for r in runs
                if r.judge_winner in ("rerun",) and r.is_rerun
                or r.judge_winner == "original" and not r.is_rerun
            )
            judged = sum(1 for r in runs if r.judge_winner is not None)
            win_rate = judge_wins / judged if judged else 0.5

            med_iters = statistics.median(iters)
            med_dur = statistics.median(durs) or 1.0
            # Composite: success matters most, then judge quality, then speed
            composite = (
                success_rate * 0.5
                + win_rate * 0.3
                + (1.0 / med_dur) * 10 * 0.2  # normalise: 10s=1.0, 100s=0.1
            )
            stats.append(ResourceStats(
                resource_id=rid,
                model=runs[-1].model,
                n_runs=len(runs),
                success_rate=success_rate,
                median_iterations=med_iters,
                median_duration_s=med_dur,
                judge_win_rate=win_rate,
                composite_score=round(composite, 4),
            ))

        stats.sort(key=lambda s: s.composite_score, reverse=True)
        return stats

    def suggest_priority_updates(self) -> Dict[str, int]:
        """
        Return {resource_id: suggested_priority} for resources whose ranking
        in the benchmark data differs from their current pool priority.
        Only emits suggestions when evidence is strong (MIN_SAMPLES met).
        """
        stats = self.analyze()
        if not stats:
            return {}

        # Current priorities from live pool
        current = _get_current_priorities()
        updates: Dict[str, int] = {}

        # Assign priorities 1..N in score order, preserving gaps
        for rank, s in enumerate(stats, start=1):
            current_p = current.get(s.resource_id)
            if current_p is None:
                continue
            # Only suggest if rank implies a different priority than current
            # Use rank * 2 so there's room between entries for manual resources
            suggested = rank * 2
            if abs(suggested - current_p) >= 2:
                updates[s.resource_id] = suggested

        return updates

    def apply_priority_updates(self, updates: Dict[str, int]) -> None:
        """Write priority updates to the personal resource_pool.json."""
        if not updates:
            return
        path = _personal_resource_pool_path()
        try:
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
            else:
                data = {"resources": {}}

            resources = data.setdefault("resources", {})
            for rid, priority in updates.items():
                resources.setdefault(rid, {})["priority"] = priority
                logger.info(f"BenchmarkStore AutoTuner: {rid} → priority {priority}")

            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"BenchmarkStore: failed to apply priority updates: {e}")

    def save_tuning_report(self) -> None:
        """Write the latest analysis + suggestions to tuning_report.json."""
        try:
            stats = self.analyze()
            suggestions = self.suggest_priority_updates()
            report = {
                "generated_at": datetime.utcnow().isoformat(),
                "resources": [asdict(s) for s in stats],
                "suggested_priority_updates": suggestions,
            }
            with open(_report_path(), "w") as f:
                json.dump(report, f, indent=2)
        except Exception as e:
            logger.warning(f"BenchmarkStore: failed to save tuning report: {e}")

    # ------------------------------------------------------------------ #
    # LLM-as-judge
    # ------------------------------------------------------------------ #

    async def judge_async(
        self,
        goal: str,
        original_answer: str,
        rerun_answer: str,
        resource_manager,
    ) -> Tuple[float, str]:
        """
        Use the fastest available free model to compare two answers.

        Returns (score, winner) where:
          score   — float 1-5 quality rating of the winner
          winner  — "original" | "rerun" | "tie"
        """
        prompt = (
            f"You are evaluating two AI-generated answers to the same task.\n\n"
            f"TASK GOAL:\n{goal[:500]}\n\n"
            f"ANSWER A:\n{original_answer[:self.JUDGE_MAX_ANSWER_LEN]}\n\n"
            f"ANSWER B:\n{rerun_answer[:self.JUDGE_MAX_ANSWER_LEN]}\n\n"
            "Compare the two answers on accuracy, completeness, and conciseness. "
            "Reply with ONLY this JSON (no markdown, no explanation):\n"
            '{"winner": "A"|"B"|"tie", "score": 1-5, "reason": "one sentence"}'
        )
        try:
            resource, _ = resource_manager.select_resource(
                tier_preference=["free", "free_api"],
                task_id="benchmark_judge",
            )
            if resource is None:
                return (3.0, "tie")

            from app.llm.llm_interface import LLMInterface
            llm = LLMInterface(resource=resource)
            response = await asyncio.wait_for(
                llm.complete_async([{"role": "user", "content": prompt}]),
                timeout=60.0,
            )
            text = (response.get("content") or "").strip()
            # Strip code fences if model wrapped the JSON
            text = text.strip("`").strip()
            if text.startswith("json"):
                text = text[4:].strip()
            parsed = json.loads(text)
            raw_winner = parsed.get("winner", "tie").strip().upper()
            winner = {"A": "original", "B": "rerun"}.get(raw_winner, "tie")
            score = float(parsed.get("score", 3))
            return (score, winner)
        except Exception as e:
            logger.debug(f"BenchmarkStore judge failed: {e}")
            return (3.0, "tie")

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _append(self, rec: ExecutionRecord) -> None:
        with open(self._log_path, "a") as f:
            f.write(json.dumps(rec.to_dict()) + "\n")

    def _load_recent(self, days: int = 30) -> List[ExecutionRecord]:
        if not self._log_path.exists():
            return []
        cutoff = datetime.utcnow() - timedelta(days=days)
        records = []
        try:
            for line in self._log_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    ts = datetime.fromisoformat(d.get("ts", "2000-01-01"))
                    if ts >= cutoff:
                        records.append(ExecutionRecord.from_dict(d))
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"BenchmarkStore: failed to read log: {e}")
        return records


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _extract_resource_id(result) -> str:
    return (result.metrics or {}).get("resource_id", "") or ""


def _extract_model(result) -> str:
    return (result.metrics or {}).get("model", "") or ""


def _extract_iterations(result) -> int:
    log = (result.metrics or {}).get("iteration_log", [])
    if log:
        return len(log)
    return (result.metrics or {}).get("iterations", 0) or 0


def _extract_duration(result) -> float:
    return float((result.metrics or {}).get("duration_seconds", 0) or 0)


def _get_free_resource_ids() -> List[str]:
    """Return resource IDs that are free-tier, enabled, and agentic-capable."""
    try:
        from app.scheduler.resource_pool import ResourceManager
        rm = ResourceManager()
        ids = []
        for rid, res in rm._resources.items():
            if not getattr(res, "enabled", True):
                continue
            tier = getattr(res, "tier", "")
            if tier not in ("free", "free_api"):
                continue
            if not rm.is_agentic_capable(rid):
                continue
            # Skip template resources
            if getattr(res, "dynamic_discovery", False) and not getattr(res, "model", None):
                continue
            ids.append(rid)
        return ids
    except Exception as e:
        logger.debug(f"BenchmarkStore: failed to get free resources: {e}")
        return []


def _get_current_priorities() -> Dict[str, int]:
    try:
        from app.scheduler.resource_pool import ResourceManager
        rm = ResourceManager()
        return {
            rid: getattr(res, "priority", 50)
            for rid, res in rm._resources.items()
        }
    except Exception:
        return {}


def _recover_goal_from_log(
    goal_hash: str, records: List[ExecutionRecord]
) -> Optional[str]:
    """Find the longest goal_preview for the given hash (best approximation)."""
    candidates = [r.goal_preview for r in records if r.goal_hash == goal_hash]
    return max(candidates, key=len) if candidates else None
