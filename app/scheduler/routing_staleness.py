"""Staleness detector — Live Success Rate vs Profiled Success Rate.

Compares observed production pass rate to the v2 capability profile,
per (model, level). When the gap exceeds 0.15 with >= 20 samples,
the cell is flagged for re-profiling.

Pure functions only — no I/O for the report itself. The caller
(``run_weekly_check``) is responsible for reading the log + profile
from disk and writing the report. Keeping the math pure makes the
detector trivially testable.

Spec: ~/.memory/research/routing_staleness_spec.md
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Local imports kept narrow — the detector should not pull in the
# full scheduler at import time. We import ExecutionRecord lazily
# inside the loader function so a unit test that builds
# ExecutionRecord-like SimpleNamespace objects doesn't need the
# scheduler runtime.

# Drift thresholds from the design doc.
DEFAULT_MIN_SAMPLES = 20
DEFAULT_DRIFT_THRESHOLD = 0.15
DEFAULT_WINDOW_DAYS = 14


@dataclass
class StalenessCheck:
    """One (model, level) check result."""
    model_id: str
    level: str
    n_samples: int
    lsr: float                          # Live Success Rate (0..1)
    psr: float                          # Profiled Success Rate (0..1)
    drift: float                        # |LSR - PSR|
    stale: bool                         # drift > threshold AND n >= min


@dataclass
class StalenessReport:
    """Output of the detector. JSON-serializable via to_dict()."""
    generated_at: str
    window_days: int
    min_samples: int
    drift_threshold: float
    checks: List[StalenessCheck]
    stale_count: int
    models_evaluated: int
    levels_evaluated: int
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "window_days": self.window_days,
            "min_samples": self.min_samples,
            "drift_threshold": self.drift_threshold,
            "checks": [
                {
                    "model_id": c.model_id,
                    "level": c.level,
                    "n_samples": c.n_samples,
                    "lsr": round(c.lsr, 3),
                    "psr": round(c.psr, 3),
                    "drift": round(c.drift, 3),
                    "stale": c.stale,
                }
                for c in self.checks
            ],
            "stale_count": self.stale_count,
            "models_evaluated": self.models_evaluated,
            "levels_evaluated": self.levels_evaluated,
            "notes": list(self.notes),
        }


# Cell → level mapping (mirrors task_router._CELL_TO_LEVEL_VALUE)
# Kept inline (not imported) to avoid a circular dependency: the
# detector is meant to be importable as a pure function, and
# task_router pulls in the full routing subsystem.

_CELL_TO_LEVEL_VALUE: Dict[str, str] = {
    "A": "L1_single_call",
    "B": "L2_multi_step",
    "C": "L2_multi_step",
    "D": "L3_feedback",
}


# ---------------------------------------------------------------------------
# Pure detector
# ---------------------------------------------------------------------------

def compute_staleness(
    records: Iterable[Any],                    # anything with .resource_id, .level, .success
    capability_profile: Dict[str, Dict[str, Dict[str, Any]]],
    *,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: Optional[datetime] = None,
) -> StalenessReport:
    """Compute per-(model, level) drift between live and profiled pass rates.

    Args:
        records: an iterable of objects with ``.resource_id``, ``.level``,
            ``.success``, ``.ts`` (ISO string). Records with a missing
            level are filtered out (legacy data, or tasks that bypassed
            the router).
        capability_profile: the v2 profile shape
            ``{model_id: {cell: stats}}``. Cells are mapped to levels
            via the design-doc ladder. The PSR is ``stats["pass"]``.
        min_samples: minimum number of production records per
            (model, level) before staleness is reported. Below this,
            drift is computed but ``stale=False``.
        drift_threshold: |LSR - PSR| above this flags the cell.
        window_days: included in the report for traceability. Not
            used for filtering here — that's the caller's job. (The
            detector accepts whatever records it's given.)
        now: optional override for ``generated_at``; defaults to
            ``datetime.now(UTC)``.

    Returns:
        StalenessReport with one StalenessCheck per (model, level)
        that has at least one observation. Records where the model
        isn't in the profile, or the level isn't a known ladder rung,
        are skipped (they can't be compared to a PSR).

    Notes:
      - The detector is *informational only*. It flags cells; it
        doesn't act on them.
      - Records that have a level but no matching profile entry
        (e.g. profile was built before the model was added) are
        skipped with a note. The weekly report carries these notes
        so the operator sees when a model is in production but
        missing from the profile.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    notes: List[str] = []

    # Group records by (model_id, level). Filter:
    #   - records with no level (legacy / un-routed)
    #   - records whose level isn't in the ladder (defensive)
    #   - records with no success bool
    by_key: Dict[Tuple[str, str], List[bool]] = defaultdict(list)
    models_seen: set = set()
    levels_seen: set = set()
    skipped_unrouted = 0
    skipped_unknown_level = 0
    skipped_old = 0

    for r in records:
        # Window filter — use the record's ts if present.
        ts_str = getattr(r, "ts", None)
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts < cutoff:
                    skipped_old += 1
                    continue
            except (ValueError, TypeError):
                pass  # tolerate malformed timestamps

        model_id = getattr(r, "resource_id", None) or getattr(r, "model", None)
        level = getattr(r, "level", None)
        success = getattr(r, "success", None)

        if not model_id or not level or success is None:
            skipped_unrouted += 1
            continue
        if level not in {"L1_single_call", "L2_multi_step",
                          "L3_feedback", "L4_orchestration"}:
            skipped_unknown_level += 1
            continue

        by_key[(model_id, level)].append(bool(success))
        models_seen.add(model_id)
        levels_seen.add(level)

    if skipped_unrouted:
        notes.append(
            f"skipped {skipped_unrouted} records without cell/level "
            "(legacy or un-routed tasks)"
        )
    if skipped_unknown_level:
        notes.append(
            f"skipped {skipped_unknown_level} records with unknown level"
        )
    if skipped_old:
        notes.append(
            f"skipped {skipped_old} records older than {window_days}d"
        )

    # For each (model, level) seen in the records, look up the PSR.
    # Profile shape: {model_id: {cell: stats}}; we need to map
    # level → cell(s). The design-doc mapping is many-to-one
    # (L2 covers both B and C). The PSR for a level is the average
    # of the profile pass rates across the cells mapped to that
    # level.
    level_to_cells: Dict[str, List[str]] = defaultdict(list)
    for cell, lvl in _CELL_TO_LEVEL_VALUE.items():
        level_to_cells[lvl].append(cell)

    checks: List[StalenessCheck] = []
    stale_count = 0
    for (model_id, level), successes in sorted(by_key.items()):
        cells = level_to_cells.get(level, [])
        # Pull PSR for each cell mapped to this level.
        psr_values: List[float] = []
        for c in cells:
            cell_stats = capability_profile.get(model_id, {}).get(c)
            if cell_stats and "pass" in cell_stats:
                psr_values.append(float(cell_stats["pass"]))
        if not psr_values:
            notes.append(
                f"{model_id} {level}: in production but not in "
                f"capability profile (cells {cells}) — re-profile to "
                f"include this (model, level)"
            )
            continue

        psr = sum(psr_values) / len(psr_values)
        n = len(successes)
        lsr = sum(successes) / n if n else 0.0
        drift = abs(lsr - psr)
        is_stale = (n >= min_samples) and (drift > drift_threshold)
        if is_stale:
            stale_count += 1
        checks.append(StalenessCheck(
            model_id=model_id,
            level=level,
            n_samples=n,
            lsr=lsr,
            psr=psr,
            drift=drift,
            stale=is_stale,
        ))

    return StalenessReport(
        generated_at=now.isoformat(),
        window_days=window_days,
        min_samples=min_samples,
        drift_threshold=drift_threshold,
        checks=checks,
        stale_count=stale_count,
        models_evaluated=len(models_seen),
        levels_evaluated=len(levels_seen),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Convenience: filter to stale-only, for the notify_owner event
# ---------------------------------------------------------------------------

def stale_cells(report: StalenessReport) -> List[StalenessCheck]:
    """Return just the checks that exceeded the drift threshold."""
    return [c for c in report.checks if c.stale]


# ---------------------------------------------------------------------------
# Loader: read execution log + profile from disk for the weekly job
# ---------------------------------------------------------------------------

def _resolve_execution_log_path() -> Path:
    """Find the BenchmarkStore's log path without importing the
    scheduler at module load time.

    The path follows the layout in benchmark_store.py:benchmark_dir()
    / "execution_log.jsonl". The home directory is read from
    ``Path.home()`` (no XDG_CONFIG_HOME override — the BenchmarkStore
    uses ``~/.memory`` directly).
    """
    return Path.home() / ".memory" / "benchmarks" / "execution_log.jsonl"


def _resolve_profile_path() -> Path:
    return Path.home() / ".memory" / "benchmarks" / "routing" / "capability_profile.json"


def load_execution_records(path: Optional[Path] = None) -> List[Any]:
    """Load ExecutionRecord objects from the JSONL log.

    Lazy import of ExecutionRecord so the detector module is usable
    from contexts that don't have the full scheduler runtime.
    """
    from app.scheduler.benchmark_store import ExecutionRecord

    p = path or _resolve_execution_log_path()
    if not p.exists():
        return []
    out: List[ExecutionRecord] = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            out.append(ExecutionRecord.from_dict(d))
        except Exception:
            continue
    return out


def load_capability_profile(path: Optional[Path] = None) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Load the v2 capability profile. Returns {} on missing file."""
    p = path or _resolve_profile_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def run_weekly_check(
    *,
    execution_log_path: Optional[Path] = None,
    profile_path: Optional[Path] = None,
    report_path: Optional[Path] = None,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> StalenessReport:
    """Weekly entry point: load log + profile, run detector, write report.

    Returns the report. The caller (the scheduler task) is responsible
    for any notification side-effects — this function just writes
    the JSON file and returns.
    """
    records = load_execution_records(execution_log_path)
    profile = load_capability_profile(profile_path)
    report = compute_staleness(
        records,
        profile,
        min_samples=min_samples,
        drift_threshold=drift_threshold,
        window_days=window_days,
    )
    out = report_path or (Path.home() / ".memory" / "benchmarks" / "routing" / "staleness_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), indent=2))
    return report