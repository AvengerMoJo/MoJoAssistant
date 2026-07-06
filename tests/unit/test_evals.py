"""
Unit tests for the evaluation system (evals/).

Tests:
- Scenario definitions are well-formed
- Check kinds are recognized
- Runner executes scenarios and evaluates checks
- Store persists and queries records
- Suites expand to correct scenarios
"""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.scheduler.evals.models import (
    EvalCheck, EvalScenario, EvalSuite, EvalRecord, CheckResult,
    EvalCategory, CheckKind, FailureClass, ComplexityLevel, ToolSchemaMode,
    CapabilitySummary, translate_legacy_level,
)
from app.scheduler.evals.scenarios import (
    ALL_SCENARIOS, get_scenario, list_scenarios,
    LOOKUP_BASIC, WRITE_BASIC, LOOKUP_THEN_WRITE, RETRY_ONCE,
    CONSTRAINT_PLAN_CHOICE, NOISY_CONTEXT_LOOKUP, LONG_HORIZON_MULTI_LOOKUP,
)
from app.scheduler.evals.suites import (
    ALL_SUITES, get_suite, list_suites,
    QUALIFICATION_FAST, QUALIFICATION_STANDARD, QUALIFICATION_REASONING,
    CHARACTERIZATION_COMPLEXITY_LADDER,
)
from app.scheduler.evals.store import EvalStore


# ---------------------------------------------------------------------------
# Scenario contract tests
# ---------------------------------------------------------------------------

class TestScenarioContracts(unittest.TestCase):
    """Validate that scenario definitions are well-formed."""

    def test_all_scenarios_have_required_fields(self):
        for sid, scenario in ALL_SCENARIOS.items():
            self.assertTrue(scenario.id, f"{sid} missing id")
            self.assertTrue(scenario.suite, f"{sid} missing suite")
            self.assertIsInstance(scenario.category, EvalCategory, f"{sid} bad category")
            self.assertTrue(scenario.task_family, f"{sid} missing task_family")
            self.assertIsInstance(scenario.complexity_level, ComplexityLevel, f"{sid} bad complexity")
            self.assertTrue(scenario.goal_template, f"{sid} missing goal_template")
            self.assertTrue(scenario.available_tools, f"{sid} missing available_tools")
            self.assertTrue(scenario.checks, f"{sid} missing checks")

    def test_all_checks_have_valid_kinds(self):
        valid_kinds = set(CheckKind)
        for sid, scenario in ALL_SCENARIOS.items():
            for check in scenario.checks:
                self.assertIn(
                    check.kind, valid_kinds,
                    f"{sid}/{check.id} has invalid kind: {check.kind}",
                )

    def test_all_checks_have_failure_classes(self):
        for sid, scenario in ALL_SCENARIOS.items():
            for check in scenario.checks:
                if check.required:
                    self.assertIsNotNone(
                        check.failure_class,
                        f"{sid}/{check.id} is required but has no failure_class",
                    )

    def test_scenario_ids_match_pattern(self):
        for sid, scenario in ALL_SCENARIOS.items():
            self.assertEqual(sid, scenario.id, f"Registry key {sid} != scenario.id {scenario.id}")
            parts = sid.split(".")
            self.assertGreaterEqual(len(parts), 2, f"ID {sid} should have at least 2 parts")

    def test_goal_templates_contain_placeholders(self):
        """Write scenarios should have {write_path} placeholder."""
        for sid, scenario in ALL_SCENARIOS.items():
            if "write" in scenario.task_family.lower():
                self.assertIn(
                    "{write_path}", scenario.goal_template,
                    f"{sid} write scenario missing {{write_path}} placeholder",
                )

    def test_get_scenario_returns_correct_scenario(self):
        s = get_scenario("qualification.fast.lookup_basic")
        self.assertEqual(s.id, "qualification.fast.lookup_basic")
        self.assertEqual(s.category, EvalCategory.QUALIFICATION)

    def test_get_scenario_raises_on_unknown(self):
        with self.assertRaises(ValueError):
            get_scenario("nonexistent.scenario")

    def test_list_scenarios_filters(self):
        all_scenarios = list_scenarios()
        self.assertGreater(len(all_scenarios), 0)

        qualification = list_scenarios(category="qualification")
        for s in qualification:
            self.assertEqual(s.category, EvalCategory.QUALIFICATION)

        fast = list_scenarios(suite="qualification_fast")
        for s in fast:
            self.assertEqual(s.suite, "qualification_fast")

    def test_scenario_relabel_matches_v2_table(self):
        """Each scenario must carry the v2 unified-ladder label per design doc.

        Locks the v2 mapping table so future drift is caught immediately.
        Per ``llm_routing_benchmark_design.md`` v2 §"Level relabeling of
        existing eval scenarios".
        """
        expected = {
            # L1 — single call
            "qualification.fast.lookup_basic":        ComplexityLevel.L1_SINGLE_CALL,
            "qualification.fast.write_basic":         ComplexityLevel.L1_SINGLE_CALL,
            "qualification.integration.bash_exec":    ComplexityLevel.L1_SINGLE_CALL,
            "qualification.integration.memory_search":ComplexityLevel.L1_SINGLE_CALL,
            # L2 — planned multi-step (no feedback loop)
            "qualification.standard.lookup_then_write":   ComplexityLevel.L2_MULTI_STEP,
            "characterization.ladder.long_horizon_multi_lookup": ComplexityLevel.L2_MULTI_STEP,
            "characterization.ladder.noisy_context_lookup":      ComplexityLevel.L2_MULTI_STEP,
            "characterization.protocol.long_write_then_answer":  ComplexityLevel.L2_MULTI_STEP,
            # L3 — feedback loop / constraint reasoning
            "qualification.standard.retry_once":           ComplexityLevel.L3_FEEDBACK,
            "qualification.reasoning.constraint_plan_choice": ComplexityLevel.L3_FEEDBACK,
        }
        for sid, expected_level in expected.items():
            s = get_scenario(sid)
            self.assertEqual(
                s.complexity_level, expected_level,
                f"{sid} expected {expected_level.value}, got {s.complexity_level.value}",
            )

    def test_v1_complexity_members_are_abolished(self):
        """No scenario may carry a v1 label — that drift is the bug A2 fixes."""
        v1_values = {"L1_basic", "L2_workflow", "L3_constrained", "L4_noisy", "L5_long_horizon"}
        for sid, scenario in ALL_SCENARIOS.items():
            self.assertNotIn(
                scenario.complexity_level.value, v1_values,
                f"{sid} still carries v1 label {scenario.complexity_level.value}",
            )

    def test_complexity_enum_has_exactly_four_members(self):
        """v2 ladder is L1/L2/L3/L4 — no more, no less."""
        self.assertEqual(
            {m.value for m in ComplexityLevel},
            {"L1_single_call", "L2_multi_step", "L3_feedback", "L4_orchestration"},
        )


# ---------------------------------------------------------------------------
# Suite tests
# ---------------------------------------------------------------------------

class TestSuites(unittest.TestCase):
    """Validate suite definitions and expansion."""

    def test_all_suites_have_required_fields(self):
        for sid, suite in ALL_SUITES.items():
            self.assertTrue(suite.id, f"{sid} missing id")
            self.assertTrue(suite.display_name, f"{sid} missing display_name")
            self.assertIsInstance(suite.category, EvalCategory, f"{sid} bad category")
            self.assertTrue(suite.default_scenarios, f"{sid} missing scenarios")

    def test_all_suite_scenarios_exist(self):
        for sid, suite in ALL_SUITES.items():
            for scenario_id in suite.default_scenarios:
                self.assertIn(
                    scenario_id, ALL_SCENARIOS,
                    f"Suite {sid} references unknown scenario {scenario_id}",
                )

    def test_qualification_fast_has_two_scenarios(self):
        suite = get_suite("qualification_fast")
        self.assertEqual(len(suite.default_scenarios), 2)
        self.assertIn("qualification.fast.lookup_basic", suite.default_scenarios)
        self.assertIn("qualification.fast.write_basic", suite.default_scenarios)

    def test_qualification_standard_adds_workflow(self):
        fast = get_suite("qualification_fast")
        standard = get_suite("qualification_standard")
        self.assertGreater(len(standard.default_scenarios), len(fast.default_scenarios))
        self.assertIn("qualification.standard.lookup_then_write", standard.default_scenarios)
        self.assertIn("qualification.standard.retry_once", standard.default_scenarios)

    def test_qualification_reasoning_adds_constraint(self):
        standard = get_suite("qualification_standard")
        reasoning = get_suite("qualification_reasoning")
        self.assertGreater(len(reasoning.default_scenarios), len(standard.default_scenarios))
        self.assertIn("qualification.reasoning.constraint_plan_choice", reasoning.default_scenarios)

    def test_complexity_ladder_has_all_levels(self):
        ladder = get_suite("characterization_complexity_ladder")
        levels = set()
        for scenario_id in ladder.default_scenarios:
            s = get_scenario(scenario_id)
            levels.add(s.complexity_level)
        self.assertIn(ComplexityLevel.L1_SINGLE_CALL, levels)
        self.assertIn(ComplexityLevel.L2_MULTI_STEP, levels)

    def test_get_suite_raises_on_unknown(self):
        with self.assertRaises(ValueError):
            get_suite("nonexistent_suite")

    def test_list_suites_filters(self):
        all_suites = list_suites()
        self.assertGreater(len(all_suites), 0)

        qualification = list_suites(category="qualification")
        for s in qualification:
            self.assertEqual(s.category, EvalCategory.QUALIFICATION)


# ---------------------------------------------------------------------------
# Model serialization tests
# ---------------------------------------------------------------------------

class TestModelSerialization(unittest.TestCase):
    """Test that models serialize and deserialize correctly."""

    def test_eval_check_roundtrip(self):
        check = EvalCheck(
            id="test_check",
            kind=CheckKind.TOOL_CALLED,
            required=True,
            failure_class=FailureClass.TOOL_NOT_CALLED,
            params={"tool_name": "smoke_lookup"},
        )
        d = check.to_dict()
        restored = EvalCheck.from_dict(d)
        self.assertEqual(restored.id, "test_check")
        self.assertEqual(restored.kind, CheckKind.TOOL_CALLED)
        self.assertTrue(restored.required)
        self.assertEqual(restored.failure_class, FailureClass.TOOL_NOT_CALLED)
        self.assertEqual(restored.params, {"tool_name": "smoke_lookup"})

    def test_eval_scenario_roundtrip(self):
        scenario = LOOKUP_BASIC
        d = scenario.to_dict()
        restored = EvalScenario.from_dict(d)
        self.assertEqual(restored.id, scenario.id)
        self.assertEqual(restored.category, scenario.category)
        self.assertEqual(restored.complexity_level, scenario.complexity_level)
        self.assertEqual(len(restored.checks), len(scenario.checks))

    def test_eval_record_roundtrip(self):
        record = EvalRecord(
            ts="2026-01-01T00:00:00",
            resource_id="test_resource",
            model="test-model",
            suite="qualification_fast",
            scenario_id="qualification.fast.lookup_basic",
            category="qualification",
            task_family="lookup",
            complexity_level="L1_basic",
            tool_schema_mode="either",
            success=True,
            checks=[{"check_id": "tool_called", "kind": "tool_called", "status": "pass"}],
            iterations_used=2,
            duration_seconds=5.0,
        )
        d = record.to_dict()
        restored = EvalRecord.from_dict(d)
        self.assertEqual(restored.resource_id, "test_resource")
        self.assertTrue(restored.success)
        self.assertEqual(restored.iterations_used, 2)

    def test_capability_summary_roundtrip(self):
        summary = CapabilitySummary(
            resource_id="test",
            model="test-model",
            qualified_for_basic_agentic=True,
            qualified_for_standard_agentic=True,
            max_reliable_complexity="L2_workflow",
            tool_accuracy=0.95,
            total_evals=10,
        )
        d = summary.to_dict()
        self.assertEqual(d["resource_id"], "test")
        self.assertTrue(d["qualified_for_basic_agentic"])
        self.assertEqual(d["max_reliable_complexity"], "L2_workflow")

    def test_translate_legacy_level_v1_to_v2(self):
        """v1 labels in persisted records must map to the v2 ladder."""
        self.assertEqual(translate_legacy_level("L1_basic"),        "L1_single_call")
        self.assertEqual(translate_legacy_level("L2_workflow"),     "L2_multi_step")
        self.assertEqual(translate_legacy_level("L3_constrained"),  "L3_feedback")
        # Noise is a model trait, not a rung — collapses to L2.
        self.assertEqual(translate_legacy_level("L4_noisy"),        "L2_multi_step")
        # L5 abolished; long_horizon planned multi-step → L2.
        self.assertEqual(translate_legacy_level("L5_long_horizon"), "L2_multi_step")
        # Already-canonical v2 labels pass through unchanged.
        self.assertEqual(translate_legacy_level("L1_single_call"),  "L1_single_call")
        self.assertEqual(translate_legacy_level("L4_orchestration"), "L4_orchestration")
        # Unknown values pass through (forward-compatible).
        self.assertEqual(translate_legacy_level("experimental_X"),  "experimental_X")

    def test_eval_record_roundtrip_legacy_label(self):
        """EvalRecord.from_dict must accept v1 labels and normalize to v2.

        Note: ``translate_legacy_level`` works at the *label* level, not
        the scenario level. A v1 record carrying ``L2_workflow`` means the
        task was self-classified at L2 difficulty — the v2 ladder collapses
        that to ``L2_multi_step``. The semantic promotion of retry_once
        (a particular *scenario*) from L2 to L3 lives in the scenario's
        declared label, not in the legacy translator.
        """
        legacy_record = {
            "ts": "2026-06-15T10:00:00",
            "resource_id": "lmstudio_ornith_35b_mtp_apex",
            "model": "ornith-1.0-35b-mtp-apex",
            "suite": "qualification_standard",
            "scenario_id": "qualification.standard.lookup_then_write",
            "category": "qualification",
            "task_family": "workflow",
            "complexity_level": "L2_workflow",  # v1 L2 label
            "tool_schema_mode": "either",
            "success": True,
            "checks": [],
            "iterations_used": 4,
            "duration_seconds": 12.5,
        }
        record = EvalRecord.from_dict(legacy_record)
        # v1 "L2_workflow" collapses to L2_multi_step (no semantic change for L2).
        self.assertEqual(record.complexity_level, "L2_multi_step")

        # v1 "L3_constrained" → L3_feedback.
        record2 = EvalRecord.from_dict({**legacy_record, "complexity_level": "L3_constrained"})
        self.assertEqual(record2.complexity_level, "L3_feedback")

    def test_eval_record_roundtrip_legacy_noisy_collapses(self):
        """The v1 'L4_noisy' label must not crash and must collapse to L2_multi_step."""
        legacy_record = {
            "ts": "2026-06-15T10:00:00",
            "resource_id": "x",
            "model": "m",
            "suite": "characterization_complexity_ladder",
            "scenario_id": "characterization.ladder.noisy_context_lookup",
            "category": "characterization",
            "task_family": "noisy_context",
            "complexity_level": "L4_noisy",  # v1 label — now a tag, not a rung
            "tool_schema_mode": "either",
            "success": True,
            "checks": [],
            "iterations_used": 3,
            "duration_seconds": 8.0,
        }
        record = EvalRecord.from_dict(legacy_record)
        self.assertEqual(record.complexity_level, "L2_multi_step")

    def test_complexity_level_enum_tolerates_legacy_values(self):
        """Direct ComplexityLevel(old) must not crash on v1 labels (spec A2:
        'ComplexityLevel(...) must not crash on old values'). Backed by the
        _missing_ hook so EvalScenario.from_dict and ad-hoc lookups work too."""
        self.assertEqual(ComplexityLevel("L1_basic"), ComplexityLevel.L1_SINGLE_CALL)
        self.assertEqual(ComplexityLevel("L2_workflow"), ComplexityLevel.L2_MULTI_STEP)
        self.assertEqual(ComplexityLevel("L3_constrained"), ComplexityLevel.L3_FEEDBACK)
        self.assertEqual(ComplexityLevel("L4_noisy"), ComplexityLevel.L2_MULTI_STEP)
        self.assertEqual(ComplexityLevel("L5_long_horizon"), ComplexityLevel.L2_MULTI_STEP)
        # canonical v2 values still resolve; unknown values still raise
        self.assertEqual(ComplexityLevel("L4_orchestration"), ComplexityLevel.L4_ORCHESTRATION)
        with self.assertRaises(ValueError):
            ComplexityLevel("not_a_real_level")

    def test_eval_record_roundtrip_canonical_label_passes_through(self):
        """Records written under v2 must round-trip unchanged."""
        v2_record = {
            "ts": "2026-07-03T00:00:00",
            "resource_id": "x",
            "model": "m",
            "suite": "qualification_fast",
            "scenario_id": "qualification.fast.lookup_basic",
            "category": "qualification",
            "task_family": "lookup",
            "complexity_level": "L1_single_call",
            "tool_schema_mode": "either",
            "success": True,
            "checks": [],
            "iterations_used": 1,
            "duration_seconds": 2.0,
        }
        record = EvalRecord.from_dict(v2_record)
        self.assertEqual(record.complexity_level, "L1_single_call")


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------

class TestEvalStore(unittest.TestCase):
    """Test eval store persistence and querying."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = Path(self.tmpdir) / "eval_log.jsonl"
        self.summary_path = Path(self.tmpdir) / "eval_summary.json"

    def _make_store(self):
        store = EvalStore.__new__(EvalStore)
        store._log_path = self.log_path
        store._summary_path = self.summary_path
        return store

    def _make_record(self, **overrides):
        defaults = {
            "ts": "2026-01-01T00:00:00",
            "resource_id": "test_resource",
            "model": "test-model",
            "suite": "qualification_fast",
            "scenario_id": "qualification.fast.lookup_basic",
            "category": "qualification",
            "task_family": "lookup",
            "complexity_level": "L1_basic",
            "tool_schema_mode": "either",
            "success": True,
            "checks": [{"check_id": "tool_called", "kind": "tool_called", "status": "pass"}],
            "iterations_used": 2,
            "duration_seconds": 5.0,
        }
        defaults.update(overrides)
        return EvalRecord(**defaults)

    def test_append_and_query(self):
        store = self._make_store()
        store.append(self._make_record())
        store.append(self._make_record(success=False, scenario_id="qualification.fast.write_basic"))

        results = store.query(resource_id="test_resource")
        self.assertEqual(len(results), 2)

    def test_query_filters(self):
        store = self._make_store()
        store.append(self._make_record(suite="qualification_fast"))
        store.append(self._make_record(suite="qualification_standard"))

        fast = store.query(suite="qualification_fast")
        self.assertEqual(len(fast), 1)
        self.assertEqual(fast[0].suite, "qualification_fast")

    def test_query_limit(self):
        store = self._make_store()
        for i in range(10):
            store.append(self._make_record(ts=f"2026-01-01T00:00:{i:02d}"))

        results = store.query(limit=5)
        self.assertEqual(len(results), 5)

    def test_get_latest(self):
        store = self._make_store()
        store.append(self._make_record(ts="2026-01-01T00:00:00"))
        store.append(self._make_record(ts="2026-01-02T00:00:00"))

        latest = store.get_latest("test_resource")
        self.assertIsNotNone(latest)
        self.assertEqual(latest.ts, "2026-01-02T00:00:00")

    def test_compute_summary(self):
        store = self._make_store()
        store.append(self._make_record(
            suite="qualification_fast", success=True, duration_seconds=5.0,
            checks=[{"check_id": "tool_called", "kind": "tool_called", "status": "pass"}],
            ts="2026-06-10T00:00:00",
        ))
        store.append(self._make_record(
            suite="qualification_fast", success=True, duration_seconds=7.0,
            checks=[{"check_id": "tool_called", "kind": "tool_called", "status": "pass"}],
            ts="2026-06-10T00:01:00",
        ))

        summary = store.compute_summary("test_resource")
        self.assertTrue(summary.qualified_for_basic_agentic)
        self.assertEqual(summary.tool_accuracy, 1.0)
        self.assertEqual(summary.total_evals, 2)

    def test_save_and_load_summary(self):
        store = self._make_store()
        summary = CapabilitySummary(
            resource_id="test", model="test-model",
            qualified_for_basic_agentic=True, total_evals=5,
        )
        store.save_summary(summary)

        loaded = store.load_summary("test")
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded.qualified_for_basic_agentic)
        self.assertEqual(loaded.total_evals, 5)

    def test_empty_query_returns_empty(self):
        store = self._make_store()
        results = store.query()
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# Check evaluation tests
# ---------------------------------------------------------------------------

class TestCheckEvaluation(unittest.TestCase):
    """Test the check evaluation logic."""

    def test_tool_called_pass(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="tc", kind=CheckKind.TOOL_CALLED, required=True,
                          failure_class=FailureClass.TOOL_NOT_CALLED,
                          params={"tool_name": "smoke_lookup"})
        log = [{"status": "tool_use", "tool_calls": ["smoke_lookup"]}]
        results = evaluate_checks([check], log, "answer", 5.0, {})
        self.assertEqual(results[0].status, "pass")

    def test_tool_called_fail(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="tc", kind=CheckKind.TOOL_CALLED, required=True,
                          failure_class=FailureClass.TOOL_NOT_CALLED,
                          params={"tool_name": "smoke_lookup"})
        log = [{"status": "tool_use", "tool_calls": ["write_file"]}]
        results = evaluate_checks([check], log, "answer", 5.0, {})
        self.assertEqual(results[0].status, "fail")
        self.assertEqual(results[0].failure_class, "tool_not_called")

    def test_final_answer_present(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="fa", kind=CheckKind.FINAL_ANSWER_PRESENT, required=True,
                          failure_class=FailureClass.FINAL_ANSWER_MISSING)
        results = evaluate_checks([check], [], "some answer", 5.0, {})
        self.assertEqual(results[0].status, "pass")

    def test_final_answer_missing(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="fa", kind=CheckKind.FINAL_ANSWER_PRESENT, required=True,
                          failure_class=FailureClass.FINAL_ANSWER_MISSING)
        results = evaluate_checks([check], [], None, 5.0, {})
        self.assertEqual(results[0].status, "fail")

    def test_final_answer_contains(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="fc", kind=CheckKind.FINAL_ANSWER_CONTAINS, required=True,
                          failure_class=FailureClass.VERIFICATION_MISMATCH,
                          params={"expected": "hello"})
        results = evaluate_checks([check], [], "hello world", 5.0, {})
        self.assertEqual(results[0].status, "pass")

    def test_final_answer_contains_fail(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="fc", kind=CheckKind.FINAL_ANSWER_CONTAINS, required=True,
                          failure_class=FailureClass.VERIFICATION_MISMATCH,
                          params={"expected": "hello"})
        results = evaluate_checks([check], [], "goodbye world", 5.0, {})
        self.assertEqual(results[0].status, "fail")

    def test_duration_under_pass(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="dur", kind=CheckKind.DURATION_UNDER, required=False,
                          params={"max_seconds": 30})
        results = evaluate_checks([check], [], "answer", 10.0, {})
        self.assertEqual(results[0].status, "pass")

    def test_duration_under_fail(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="dur", kind=CheckKind.DURATION_UNDER, required=True,
                          failure_class=FailureClass.DURATION_EXCEEDED,
                          params={"max_seconds": 10})
        results = evaluate_checks([check], [], "answer", 30.0, {})
        self.assertEqual(results[0].status, "fail")

    def test_retry_after_failure_pass(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="retry", kind=CheckKind.RETRY_AFTER_FAILURE, required=True,
                          failure_class=FailureClass.TOOL_NOT_CALLED,
                          params={"tool_name": "smoke_fail_once", "min_calls": 2})
        log = [
            {"status": "tool_use", "tool_calls": ["smoke_fail_once"]},
            {"status": "tool_use", "tool_calls": ["smoke_fail_once"]},
        ]
        results = evaluate_checks([check], log, "answer", 5.0, {})
        self.assertEqual(results[0].status, "pass")

    def test_retry_after_failure_fail(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="retry", kind=CheckKind.RETRY_AFTER_FAILURE, required=True,
                          failure_class=FailureClass.TOOL_NOT_CALLED,
                          params={"tool_name": "smoke_fail_once", "min_calls": 2})
        log = [{"status": "tool_use", "tool_calls": ["smoke_fail_once"]}]
        results = evaluate_checks([check], log, "answer", 5.0, {})
        self.assertEqual(results[0].status, "fail")

    def test_file_written_exact(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="fw", kind=CheckKind.FILE_WRITTEN_EXACT, required=True,
                          failure_class=FailureClass.XML_TOOL_LEAKAGE,
                          params={"expected_content": "smoke_test_ok"})
        artifacts = {"file_content": "smoke_test_ok"}
        results = evaluate_checks([check], [], "answer", 5.0, artifacts)
        self.assertEqual(results[0].status, "pass")

    def test_file_written_exact_mismatch(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="fw", kind=CheckKind.FILE_WRITTEN_EXACT, required=True,
                          failure_class=FailureClass.XML_TOOL_LEAKAGE,
                          params={"expected_content": "smoke_test_ok"})
        artifacts = {"file_content": "wrong_content"}
        results = evaluate_checks([check], [], "answer", 5.0, artifacts)
        self.assertEqual(results[0].status, "fail")

    def test_min_tool_call_count(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="min", kind=CheckKind.MIN_TOOL_CALL_COUNT, required=True,
                          failure_class=FailureClass.TOOL_NOT_CALLED,
                          params={"tool_name": "smoke_lookup", "min_count": 2})
        log = [
            {"status": "tool_use", "tool_calls": ["smoke_lookup"]},
            {"status": "tool_use", "tool_calls": ["smoke_lookup"]},
        ]
        results = evaluate_checks([check], log, "answer", 5.0, {})
        self.assertEqual(results[0].status, "pass")

    def test_backend_available(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="be", kind=CheckKind.BACKEND_AVAILABLE, required=False)
        results = evaluate_checks([check], [], "answer", 5.0, {"backend_available": True})
        self.assertEqual(results[0].status, "pass")

    def test_backend_unavailable(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="be", kind=CheckKind.BACKEND_AVAILABLE, required=False)
        results = evaluate_checks([check], [], "answer", 5.0, {"backend_available": False})
        self.assertEqual(results[0].status, "skip")
        self.assertEqual(results[0].failure_class, "tool_backend_unavailable")

    # --- TOOL_ARG_CONTAINS ---

    def test_tool_arg_contains_pass(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="tac", kind=CheckKind.TOOL_ARG_CONTAINS, required=True,
                          failure_class=FailureClass.WRONG_TOOL_ARGS,
                          params={"tool_name": "smoke_dispatch", "arg_name": "goal",
                                  "expected_substrings": ["done when", "verify by"]})
        log = [{"status": "tool_use", "tool_calls": ["smoke_dispatch"],
                "tool_call_details": [{"name": "smoke_dispatch",
                                       "arguments": {"goal": "Research X. Done when: report written. Verify by: reading it."}}]}]
        results = evaluate_checks([check], log, "answer", 5.0, {})
        self.assertEqual(results[0].status, "pass")

    def test_tool_arg_contains_fail_missing_substring(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="tac", kind=CheckKind.TOOL_ARG_CONTAINS, required=True,
                          failure_class=FailureClass.WRONG_TOOL_ARGS,
                          params={"tool_name": "smoke_dispatch", "arg_name": "goal",
                                  "expected_substrings": ["done when", "verify by"]})
        log = [{"status": "tool_use", "tool_calls": ["smoke_dispatch"],
                "tool_call_details": [{"name": "smoke_dispatch",
                                       "arguments": {"goal": "Research X. Done when: report written."}}]}]
        results = evaluate_checks([check], log, "answer", 5.0, {})
        self.assertEqual(results[0].status, "fail")
        self.assertEqual(results[0].failure_class, "wrong_tool_args")

    def test_tool_arg_contains_fail_no_details(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="tac", kind=CheckKind.TOOL_ARG_CONTAINS, required=True,
                          failure_class=FailureClass.WRONG_TOOL_ARGS,
                          params={"tool_name": "smoke_dispatch", "arg_name": "goal",
                                  "expected_substrings": ["done when"]})
        # Old-style log without tool_call_details -> cannot verify -> fail.
        log = [{"status": "tool_use", "tool_calls": ["smoke_dispatch"]}]
        results = evaluate_checks([check], log, "answer", 5.0, {})
        self.assertEqual(results[0].status, "fail")

    # --- TOOL_ORDER ---

    def test_tool_order_pass(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="to", kind=CheckKind.TOOL_ORDER, required=True,
                          failure_class=FailureClass.WRONG_ORDER,
                          params={"first_tool": "smoke_dispatch", "then_tool": "write_file"})
        log = [
            {"status": "tool_use", "tool_calls": ["smoke_dispatch"]},
            {"status": "tool_use", "tool_calls": ["write_file"]},
        ]
        results = evaluate_checks([check], log, "answer", 5.0, {})
        self.assertEqual(results[0].status, "pass")

    def test_tool_order_fail_wrong_order(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="to", kind=CheckKind.TOOL_ORDER, required=True,
                          failure_class=FailureClass.WRONG_ORDER,
                          params={"first_tool": "smoke_dispatch", "then_tool": "write_file"})
        log = [
            {"status": "tool_use", "tool_calls": ["write_file"]},
            {"status": "tool_use", "tool_calls": ["smoke_dispatch"]},
        ]
        results = evaluate_checks([check], log, "answer", 5.0, {})
        self.assertEqual(results[0].status, "fail")
        self.assertEqual(results[0].failure_class, "wrong_order")

    def test_tool_order_fail_first_missing(self):
        from app.scheduler.evals.runner import evaluate_checks
        check = EvalCheck(id="to", kind=CheckKind.TOOL_ORDER, required=True,
                          failure_class=FailureClass.WRONG_ORDER,
                          params={"first_tool": "smoke_dispatch", "then_tool": "write_file"})
        log = [{"status": "tool_use", "tool_calls": ["write_file"]}]
        results = evaluate_checks([check], log, "answer", 5.0, {})
        self.assertEqual(results[0].status, "fail")
        self.assertEqual(results[0].failure_class, "wrong_order")


if __name__ == "__main__":
    unittest.main()
