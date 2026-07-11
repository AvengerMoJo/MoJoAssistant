"""Tests for routing_staleness (W2.2)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from app.scheduler.routing_staleness import (  # noqa: E402
    compute_staleness, stale_cells, run_weekly_check, format_weekly_summary,
    StalenessReport, StalenessCheck,
    DEFAULT_MIN_SAMPLES, DEFAULT_DRIFT_THRESHOLD, DEFAULT_WINDOW_DAYS,
    load_execution_records, load_capability_profile,
)


def _rec(model, level, success, days_ago=0, ts=None):
    """Build a record-like object. Pass either days_ago or explicit ts."""
    if ts is None:
        ts_dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        ts_str = ts_dt.isoformat()
    else:
        ts_str = ts
    return SimpleNamespace(
        resource_id=model, model=model, level=level,
        success=success, ts=ts_str,
    )


# A complete v2 profile covering all 4 levels, used in most tests.
def _profile():
    return {
        "model_a": {
            "A": {"pass": 0.90, "total": 10, "success": 9, "failure_modes": {}},
            "B": {"pass": 0.85, "total": 10, "success": 8, "failure_modes": {}},
            "C": {"pass": 0.85, "total": 10, "success": 8, "failure_modes": {}},
            "D": {"pass": 0.50, "total": 10, "success": 5, "failure_modes": {}},
        },
        "model_b": {
            "A": {"pass": 0.95, "total": 10, "success": 9, "failure_modes": {}},
            "B": {"pass": 0.80, "total": 10, "success": 8, "failure_modes": {}},
            "C": {"pass": 0.80, "total": 10, "success": 8, "failure_modes": {}},
            "D": {"pass": 0.40, "total": 10, "success": 4, "failure_modes": {}},
        },
    }


class TestComputeStaleness:
    """The pure detector: per-(model, level) LSR vs PSR drift."""

    def test_no_records_empty_report(self):
        report = compute_staleness([], _profile())
        assert report.checks == []
        assert report.stale_count == 0
        assert report.models_evaluated == 0
        assert report.levels_evaluated == 0

    def test_below_min_samples_not_stale(self):
        # 19 records, all failures (drift huge) — but below min_samples.
        records = [_rec("model_a", "L1_single_call", False) for _ in range(19)]
        report = compute_staleness(records, _profile())
        assert len(report.checks) == 1
        check = report.checks[0]
        assert check.n_samples == 19
        assert check.drift > 0.15  # 0.0 - 0.9 = 0.9
        assert check.stale is False  # but stale=False because n < min

    def test_above_min_samples_stale(self):
        # 25 records, all failures, model PSR=0.9 → drift=0.9 → stale.
        records = [_rec("model_a", "L1_single_call", False) for _ in range(25)]
        report = compute_staleness(records, _profile(), min_samples=20)
        assert len(report.checks) == 1
        check = report.checks[0]
        assert check.n_samples == 25
        assert check.lsr == 0.0
        assert check.psr == 0.9
        assert abs(check.drift - 0.9) < 1e-6  # float-tolerant
        assert check.stale is True
        assert report.stale_count == 1

    def test_drift_below_threshold_not_stale(self):
        # 25 records, 22 pass / 3 fail → LSR=0.88, PSR=0.90, drift≈0.02.
        records = (
            [_rec("model_a", "L1_single_call", True) for _ in range(22)]
            + [_rec("model_a", "L1_single_call", False) for _ in range(3)]
        )
        report = compute_staleness(records, _profile(), min_samples=20)
        assert len(report.checks) == 1
        check = report.checks[0]
        # Use approximate comparison — 22/25 = 0.88 exactly but the
        # PSR=0.9 was stored as 0.9 and PSR=0.88 happens at the
        # 1/3=0.333 step. Float math gives us 0.020000000000000018.
        assert abs(check.drift - 0.02) < 1e-6
        assert check.stale is False
        assert report.stale_count == 0

    def test_legacy_records_without_level_are_skipped(self):
        # No level → not bucketed. Should not show in checks.
        records = [
            SimpleNamespace(resource_id="m", model="m", level=None, success=True, ts=None),
            SimpleNamespace(resource_id="m", model="m", level="", success=True, ts=None),
        ]
        report = compute_staleness(records, _profile())
        assert report.checks == []
        # The skipped count is reflected in a note for the operator.
        assert any("without cell/level" in n for n in report.notes)

    def test_unknown_level_skipped(self):
        # Defensive: a level not in the design-doc ladder.
        records = [_rec("model_a", "L99_future", True) for _ in range(25)]
        report = compute_staleness(records, _profile())
        assert report.checks == []
        # The note calls out unknown-level records so the operator
        # sees a non-ladder level name in production.
        assert any("unknown level" in n for n in report.notes)

    def test_model_in_production_not_in_profile_emits_note(self):
        # model_c isn't in the profile — should be skipped with a note.
        records = [_rec("model_c", "L1_single_call", True) for _ in range(25)]
        report = compute_staleness(records, _profile())
        assert report.checks == []
        # The note calls out the missing (model, level) so the
        # operator knows a re-profile is needed to add the model.
        assert any("model_c" in n and "capability profile" in n for n in report.notes)

    def test_psr_average_across_cells_mapped_to_same_level(self):
        # L2 covers both B and C in the v2 ladder. PSR for L2 is the
        # average of the B and C profile entries.
        # model_a: B=0.85, C=0.85 → L2 PSR = 0.85.
        # 25 records, 20 pass / 5 fail → LSR = 0.80. drift = 0.05.
        records = (
            [_rec("model_a", "L2_multi_step", True) for _ in range(20)]
            + [_rec("model_a", "L2_multi_step", False) for _ in range(5)]
        )
        report = compute_staleness(records, _profile(), min_samples=20)
        check = next(c for c in report.checks if c.level == "L2_multi_step")
        assert check.psr == 0.85
        assert check.lsr == 0.80
        assert abs(check.drift - 0.05) < 1e-6
        assert check.stale is False

    def test_psr_diverges_between_B_and_C_for_same_level(self):
        # If profile has B=1.0 and C=0.6 (mismatched), L2 PSR is the
        # average. The detector surfaces this as a "this level is
        # weird" signal — operator should investigate.
        profile = {
            "model_x": {
                "B": {"pass": 1.0, "total": 10, "success": 10, "failure_modes": {}},
                "C": {"pass": 0.6, "total": 10, "success": 6, "failure_modes": {}},
            }
        }
        records = [_rec("model_x", "L2_multi_step", True) for _ in range(25)]
        report = compute_staleness(records, profile)
        check = report.checks[0]
        assert check.psr == 0.8  # (1.0 + 0.6) / 2
        assert check.lsr == 1.0
        assert abs(check.drift - 0.2) < 1e-6
        assert check.stale is True

    def test_multiple_models_separately(self):
        # model_a: 25 records, 20 pass, PSR=0.9, LSR=0.8, drift=0.1 → not stale.
        # model_b: 25 records, 5 pass, PSR=0.95, LSR=0.2, drift=0.75 → stale.
        records = (
            [_rec("model_a", "L1_single_call", True) for _ in range(20)]
            + [_rec("model_a", "L1_single_call", False) for _ in range(5)]
            + [_rec("model_b", "L1_single_call", True) for _ in range(5)]
            + [_rec("model_b", "L1_single_call", False) for _ in range(20)]
        )
        report = compute_staleness(records, _profile(), min_samples=20)
        a = next(c for c in report.checks if c.model_id == "model_a")
        b = next(c for c in report.checks if c.model_id == "model_b")
        assert a.stale is False
        assert b.stale is True
        assert report.stale_count == 1
        assert report.models_evaluated == 2

    def test_drift_threshold_exclusive(self):
        # drift > threshold is stale; drift == threshold is not (strict >).
        # 25 records, 19 pass / 6 fail → LSR=0.76. PSR=0.90.
        # drift = |0.76 - 0.90| = 0.14. Below 0.15 → not stale.
        # Now test the boundary: 18 pass / 7 fail → LSR=0.72. drift=0.18.
        # Above 0.15 → stale.
        records_below = (
            [_rec("model_a", "L1_single_call", True) for _ in range(19)]
            + [_rec("model_a", "L1_single_call", False) for _ in range(6)]
        )
        r_below = compute_staleness(records_below, _profile(), min_samples=20)
        assert abs(r_below.checks[0].drift - 0.14) < 1e-6
        assert r_below.checks[0].stale is False

        records_above = (
            [_rec("model_a", "L1_single_call", True) for _ in range(18)]
            + [_rec("model_a", "L1_single_call", False) for _ in range(7)]
        )
        r_above = compute_staleness(records_above, _profile(), min_samples=20)
        assert abs(r_above.checks[0].drift - 0.18) < 1e-6
        assert r_above.checks[0].stale is True

    def test_window_filter_excludes_old_records(self):
        # Records older than the window are skipped — a sample from
        # 30 days ago shouldn't pollute today's staleness report.
        old = [_rec("model_a", "L1_single_call", True) for _ in range(40)]
        new = [_rec("model_a", "L1_single_call", True) for _ in range(5)]
        for r in old:
            r.ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        records = old + new
        report = compute_staleness(records, _profile(),
                                  min_samples=5, window_days=14)
        # Only the 5 in-window records count.
        assert report.checks[0].n_samples == 5
        # The skipped-old note tells the operator.
        assert any("older than 14d" in n for n in report.notes)

    def test_malformed_timestamp_not_excluded(self):
        # A record with a bad ts string falls through the window
        # filter (no exception) and counts toward the bucket.
        records = [
            _rec("model_a", "L1_single_call", True, ts="not-a-date"),
        ] + [_rec("model_a", "L1_single_call", True) for _ in range(24)]
        report = compute_staleness(records, _profile(), min_samples=20)
        assert report.checks[0].n_samples == 25

    def test_levels_evaluated_counts_distinct_levels(self):
        # Records span L1 and L2 → levels_evaluated=2.
        records = (
            [_rec("model_a", "L1_single_call", True) for _ in range(25)]
            + [_rec("model_a", "L2_multi_step", True) for _ in range(25)]
        )
        report = compute_staleness(records, _profile())
        assert report.levels_evaluated == 2
        assert report.models_evaluated == 1

    def test_serialization_round_trip(self):
        records = (
            [_rec("model_a", "L1_single_call", True) for _ in range(20)]
            + [_rec("model_a", "L1_single_call", False) for _ in range(5)]
            + [_rec("model_b", "L2_multi_step", True) for _ in range(25)]
        )
        report = compute_staleness(records, _profile())
        d = report.to_dict()
        # Round-trip through JSON.
        s = json.dumps(d)
        d2 = json.loads(s)
        assert d2["stale_count"] == report.stale_count
        assert d2["models_evaluated"] == report.models_evaluated
        assert len(d2["checks"]) == len(report.checks)
        for orig, recovered in zip(report.checks, d2["checks"]):
            assert orig.model_id == recovered["model_id"]
            assert orig.level == recovered["level"]
            assert orig.stale == recovered["stale"]


class TestStaleCells:
    def test_returns_only_stale(self):
        # Three checks: one stale, two clean.
        checks = [
            StalenessCheck("m1", "L1", 30, 0.5, 0.9, 0.4, stale=True),
            StalenessCheck("m1", "L2", 30, 0.85, 0.9, 0.05, stale=False),
            StalenessCheck("m2", "L3", 30, 0.95, 0.9, 0.05, stale=False),
        ]
        report = StalenessReport(
            generated_at="2026-07-11T00:00:00+00:00",
            window_days=14, min_samples=20, drift_threshold=0.15,
            checks=checks, stale_count=1,
            models_evaluated=2, levels_evaluated=3,
        )
        result = stale_cells(report)
        assert len(result) == 1
        assert result[0].model_id == "m1"
        assert result[0].level == "L1"

    def test_no_stale_returns_empty(self):
        checks = [
            StalenessCheck("m1", "L1", 30, 0.85, 0.9, 0.05, stale=False),
        ]
        report = StalenessReport(
            generated_at="2026-07-11T00:00:00+00:00",
            window_days=14, min_samples=20, drift_threshold=0.15,
            checks=checks, stale_count=0,
            models_evaluated=1, levels_evaluated=1,
        )
        assert stale_cells(report) == []


class TestRunWeeklyCheck:
    """End-to-end: load log + profile from disk, run detector, write report."""

    def _write_profile(self, tmpdir, profile):
        p = Path(tmpdir) / "capability_profile.json"
        p.write_text(json.dumps(profile))
        return p

    def _write_log(self, tmpdir, records):
        p = Path(tmpdir) / "execution_log.jsonl"
        with p.open("w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return p

    def test_end_to_end_with_real_files(self):
        with tempfile.TemporaryDirectory() as td:
            profile = _profile()
            profile_path = self._write_profile(td, profile)
            log_records = [
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "task_id": f"t{i}",
                    "goal_hash": "abc", "goal_preview": "x",
                    "role_id": None, "resource_id": "model_a",
                    "model": "model_a", "success": i < 5,  # 5/25 pass → LSR=0.2
                    "iterations": 1, "duration_s": 1.0,
                    "final_answer_len": 0, "final_answer_hash": "",
                    "is_rerun": False,
                    "cell": "A", "level": "L1_single_call",
                }
                for i in range(25)
            ]
            log_path = self._write_log(td, log_records)
            report_path = Path(td) / "out" / "staleness.json"

            report = run_weekly_check(
                execution_log_path=log_path,
                profile_path=profile_path,
                report_path=report_path,
                min_samples=20,
            )

            assert report_path.exists()
            d = json.loads(report_path.read_text())
            assert d["stale_count"] == 1
            # model_a L1: 5/25 pass → 0.2 vs 0.9 → drift 0.7 → stale.
            check = d["checks"][0]
            assert check["model_id"] == "model_a"
            assert check["level"] == "L1_single_call"
            assert check["stale"] is True
            assert check["n_samples"] == 25

    def test_no_log_file_no_crash(self):
        with tempfile.TemporaryDirectory() as td:
            profile_path = self._write_profile(td, _profile())
            report_path = Path(td) / "out.json"
            report = run_weekly_check(
                execution_log_path=Path(td) / "missing.jsonl",
                profile_path=profile_path,
                report_path=report_path,
            )
            assert report.checks == []
            assert report.stale_count == 0
            assert report_path.exists()
            d = json.loads(report_path.read_text())
            assert d["checks"] == []
            assert d["stale_count"] == 0

    def test_no_profile_file_no_crash(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = self._write_log(td, [
                {"ts": datetime.now(timezone.utc).isoformat(),
                 "task_id": "t1", "goal_hash": "abc", "goal_preview": "x",
                 "role_id": None, "resource_id": "m", "model": "m",
                 "success": True, "iterations": 1, "duration_s": 1.0,
                 "final_answer_len": 0, "final_answer_hash": "",
                 "is_rerun": False, "cell": "A", "level": "L1_single_call"},
            ])
            report = run_weekly_check(
                execution_log_path=log_path,
                profile_path=Path(td) / "missing_profile.json",
                report_path=Path(td) / "out.json",
            )
            # The model is in production but not in profile → note.
            assert any("not in capability profile" in n for n in report.notes)


class TestLoaders:
    def test_load_execution_records(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "log.jsonl"
            rec = {
                "ts": "2026-07-11T00:00:00",
                "task_id": "t1", "goal_hash": "abc", "goal_preview": "x",
                "role_id": None, "resource_id": "m", "model": "m",
                "success": True, "iterations": 1, "duration_s": 1.0,
                "final_answer_len": 0, "final_answer_hash": "",
                "is_rerun": False, "cell": "A", "level": "L1_single_call",
            }
            log.write_text(json.dumps(rec) + "\n" + "garbage line\n")
            records = load_execution_records(log)
            assert len(records) == 1
            assert records[0].cell == "A"
            assert records[0].level == "L1_single_call"

    def test_load_capability_profile(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cap.json"
            p.write_text(json.dumps({"m1": {"A": {"pass": 0.8}}}))
            profile = load_capability_profile(p)
            assert profile["m1"]["A"]["pass"] == 0.8

    def test_load_capability_profile_missing(self):
        with tempfile.TemporaryDirectory() as td:
            profile = load_capability_profile(Path(td) / "missing.json")
            assert profile == {}


class TestFormatWeeklySummary:
    """The weekly command writes this to stdout for log-grep."""

    def test_no_stale_summary_is_clean(self):
        # Build a clean report by running through compute_staleness.
        records = [_rec("model_a", "L1_single_call", True) for _ in range(25)]
        report = compute_staleness(records, _profile())
        summary = format_weekly_summary(report)
        assert "STALENESS OK" in summary
        assert "0 stale" in summary
        assert "STALENESS ALERT" not in summary

    def test_stale_summary_lists_cells(self):
        records = (
            [_rec("model_a", "L1_single_call", True) for _ in range(5)]
            + [_rec("model_a", "L1_single_call", False) for _ in range(20)]
        )
        report = compute_staleness(records, _profile(), min_samples=20)
        summary = format_weekly_summary(report)
        assert "STALENESS ALERT" in summary
        assert "1 stale" in summary
        # Cell details in the summary.
        assert "model_a" in summary
        assert "L1_single_call" in summary
        assert "drift=" in summary


if __name__ == "__main__":
    unittest.main()