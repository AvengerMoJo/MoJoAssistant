"""
Evaluation store — append-only JSONL persistence and aggregate summaries.

Storage layout:
  ~/.memory/benchmarks/eval_log.jsonl   — append-only evaluation records
  ~/.memory/benchmarks/eval_summary.json — cached capability summaries

This is separate from the production BenchmarkStore (execution_log.jsonl)
so evaluation runs don't pollute task-rerun history.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.scheduler.evals.models import (
    EvalRecord, CapabilitySummary, ComplexityLevel,
)

logger = logging.getLogger(__name__)


def _benchmarks_dir() -> Path:
    from app.config.paths import get_memory_subpath
    p = Path(get_memory_subpath("benchmarks"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _eval_log_path() -> Path:
    return _benchmarks_dir() / "eval_log.jsonl"


def _eval_summary_path() -> Path:
    return _benchmarks_dir() / "eval_summary.json"


class EvalStore:
    """Append-only store for evaluation records with summary aggregation."""

    def __init__(self):
        self._log_path = _eval_log_path()
        self._summary_path = _eval_summary_path()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, record: EvalRecord) -> None:
        """Append one evaluation record to the log."""
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"EvalStore: failed to append record: {e}")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query(
        self,
        resource_id: Optional[str] = None,
        suite: Optional[str] = None,
        scenario_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[EvalRecord]:
        """Query evaluation records with optional filters."""
        if not self._log_path.exists():
            return []

        records = []
        try:
            for line in self._log_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if resource_id and d.get("resource_id") != resource_id:
                        continue
                    if suite and d.get("suite") != suite:
                        continue
                    if scenario_id and d.get("scenario_id") != scenario_id:
                        continue
                    if category and d.get("category") != category:
                        continue
                    records.append(EvalRecord.from_dict(d))
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"EvalStore: failed to read eval log: {e}")

        return records[-limit:]

    def get_latest(
        self,
        resource_id: str,
        suite: Optional[str] = None,
    ) -> Optional[EvalRecord]:
        """Get the most recent eval record for a resource."""
        return next(iter(reversed(self.query(resource_id=resource_id, suite=suite, limit=1))), None)

    # ------------------------------------------------------------------
    # Summary aggregation
    # ------------------------------------------------------------------

    def compute_summary(
        self,
        resource_id: str,
        window_days: int = 30,
    ) -> CapabilitySummary:
        """Compute a capability summary from recent eval history."""
        cutoff = datetime.now(UTC) - timedelta(days=window_days)
        records = [
            r for r in self.query(resource_id=resource_id, limit=500)
            if _parse_ts(r.ts) and _parse_ts(r.ts) >= cutoff
        ]

        if not records:
            return CapabilitySummary(resource_id=resource_id, model="", total_evals=0)

        model = records[-1].model

        # Group by suite
        by_suite: Dict[str, List[EvalRecord]] = {}
        for r in records:
            by_suite.setdefault(r.suite, []).append(r)

        summary = CapabilitySummary(
            resource_id=resource_id,
            model=model,
            total_evals=len(records),
            last_evaluated_at=records[-1].ts,
        )

        # Qualification flags (all runs must pass)
        fast_runs = by_suite.get("qualification_fast", [])
        if fast_runs:
            summary.qualified_for_basic_agentic = all(r.success for r in fast_runs)
            summary.median_fast_gate_s = _median([r.duration_seconds for r in fast_runs])

        standard_runs = by_suite.get("qualification_standard", [])
        if standard_runs:
            summary.qualified_for_standard_agentic = all(r.success for r in standard_runs)
            summary.median_standard_agentic_s = _median([r.duration_seconds for r in standard_runs])

        reasoning_runs = by_suite.get("qualification_reasoning", [])
        if reasoning_runs:
            summary.qualified_for_reasoning_tasks = all(r.success for r in reasoning_runs)

        # Max reliable complexity
        summary.max_reliable_complexity = _compute_max_complexity(records)

        # Tool accuracy: fraction of tool_called checks that passed
        tool_checks = [
            c for r in records for c in r.checks
            if isinstance(c, dict) and c.get("kind") == "tool_called"
        ]
        if tool_checks:
            summary.tool_accuracy = sum(
                1 for c in tool_checks if c.get("status") == "pass"
            ) / len(tool_checks)

        # Retry recovery rate: fraction of retry_after_failure checks that passed
        retry_checks = [
            c for r in records for c in r.checks
            if isinstance(c, dict) and c.get("kind") == "retry_after_failure"
        ]
        if retry_checks:
            summary.retry_recovery_rate = sum(
                1 for c in retry_checks if c.get("status") == "pass"
            ) / len(retry_checks)

        # Constraint accuracy: fraction of final_answer_contains checks that passed
        constraint_checks = [
            c for r in records for c in r.checks
            if isinstance(c, dict) and c.get("kind") == "final_answer_contains"
        ]
        if constraint_checks:
            summary.constraint_accuracy = sum(
                1 for c in constraint_checks if c.get("status") == "pass"
            ) / len(constraint_checks)

        return summary

    def save_summary(self, summary: CapabilitySummary) -> None:
        """Persist a capability summary to the summary cache."""
        try:
            data = {}
            if self._summary_path.exists():
                data = json.loads(self._summary_path.read_text(encoding="utf-8"))
            data[summary.resource_id] = summary.to_dict()
            self._summary_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"EvalStore: failed to save summary: {e}")

    def load_summary(self, resource_id: str) -> Optional[CapabilitySummary]:
        """Load a cached capability summary."""
        if not self._summary_path.exists():
            return None
        try:
            data = json.loads(self._summary_path.read_text(encoding="utf-8"))
            d = data.get(resource_id)
            if d:
                return CapabilitySummary(**{
                    k: d.get(k) for k in CapabilitySummary.__dataclass_fields__ if k in d
                })
        except Exception:
            pass
        return None

    def list_summaries(self) -> Dict[str, CapabilitySummary]:
        """Load all cached capability summaries."""
        if not self._summary_path.exists():
            return {}
        try:
            data = json.loads(self._summary_path.read_text(encoding="utf-8"))
            return {
                rid: CapabilitySummary(**{
                    k: d.get(k) for k in CapabilitySummary.__dataclass_fields__ if k in d
                })
                for rid, d in data.items()
                if isinstance(d, dict)
            }
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts(ts_str: str) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        parsed = datetime.fromisoformat(ts_str)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except Exception:
        return None


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return round(statistics.median(values), 2)


def _compute_max_complexity(records: List[EvalRecord]) -> Optional[str]:
    """Determine the highest complexity level where all runs succeeded."""
    complexity_order = [
        ComplexityLevel.L1_BASIC,
        ComplexityLevel.L2_WORKFLOW,
        ComplexityLevel.L3_CONSTRAINED,
        ComplexityLevel.L4_NOISY,
        ComplexityLevel.L5_LONG_HORIZON,
    ]
    highest = None
    for level in complexity_order:
        level_records = [r for r in records if r.complexity_level == level.value]
        if level_records and all(r.success for r in level_records):
            highest = level.value
    return highest
