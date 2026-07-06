"""Tests for task router."""

import pytest
from app.scheduler.task_router import compute_cell, TaskRouter, RoutingResult
from app.scheduler.evals.models import (
    FailureClass, classify_failure, SLOW_DURATION_S, TIMEOUT_DURATION_S,
)
from app.scheduler.routing_profile import (
    TaskRecord, aggregate_profile, derive_routing_table, load_profile,
    from_legacy_summary,
)


# ---------------------------------------------------------------------------
# classify_failure — pure-function behavior (A7)
# ---------------------------------------------------------------------------

class TestClassifyFailure:
    """The pure classifier is the input contract for the profiler.

    Locks the routing-relevant semantics: leakage / malformed / slow /
    timeout / verification_mismatch / clean-pass.
    """

    def test_clean_pass_returns_none(self):
        # Fast success, no error, clean response — no signal worth bucketing.
        assert classify_failure(success=True, elapsed_s=2.0, response="answer") is None

    def test_xml_leakage_in_response_is_hard_disqualifier(self):
        fc = classify_failure(
            success=False, elapsed_s=5.0,
            response="I'll call <functionCall>...</functionCall>",
        )
        assert fc is FailureClass.XML_TOOL_LEAKAGE

    def test_xml_leakage_detected_even_on_success(self):
        # Leakage in the body of an otherwise-correct answer is still a DQ.
        fc = classify_failure(
            success=True, elapsed_s=5.0,
            response="Here you go <functionCall name='x'>",
        )
        assert fc is FailureClass.XML_TOOL_LEAKAGE

    def test_slow_success_becomes_final_answer_slow(self):
        # Above SLOW but below TIMEOUT, succeeded → slow-but-capable signal.
        fc = classify_failure(success=True, elapsed_s=SLOW_DURATION_S + 1)
        assert fc is FailureClass.FINAL_ANSWER_SLOW

    def test_very_long_becomes_timeout(self):
        # Above TIMEOUT — even on success, this is a budget signal.
        fc = classify_failure(success=True, elapsed_s=TIMEOUT_DURATION_S + 5)
        assert fc is FailureClass.TIMEOUT

    def test_error_string_timeout(self):
        fc = classify_failure(success=False, elapsed_s=10.0, error="LLM timed out after 60s")
        assert fc is FailureClass.TIMEOUT

    def test_error_string_backend_unavailable(self):
        fc = classify_failure(success=False, elapsed_s=10.0, error="backend unavailable")
        assert fc is FailureClass.TOOL_BACKEND_UNAVAILABLE

    def test_error_string_malformed_arguments(self):
        fc = classify_failure(success=False, elapsed_s=10.0, error="invalid arguments")
        assert fc is FailureClass.MALFORMED_ARGUMENTS

    def test_failed_no_signal_is_verification_mismatch(self):
        # Task failed but no error string and no duration signal → the
        # verification itself rejected the answer. Capability ceiling.
        fc = classify_failure(success=False, elapsed_s=5.0, response="I tried.")
        assert fc is FailureClass.VERIFICATION_MISMATCH


# ---------------------------------------------------------------------------
# Routing profile aggregation (A7)
# ---------------------------------------------------------------------------

def _record(cell, model, success, elapsed=2.0, fc=None, error=None):
    return TaskRecord(
        task_id=f"{cell}_{model}", cell=cell, resource_id=model,
        success=success, elapsed_s=elapsed, error=error, failure_class=fc,
    )


class TestAggregateProfile:
    def test_pass_rate_and_failure_modes(self):
        # 5 tasks: 3 pass, 2 fail (both leakage). pass=0.6, leakage rate
        # over failed pop = 1.0.
        records = (
            [_record("A", "m1", success=True)] * 3
            + [_record("A", "m1", success=False, fc="xml_tool_leakage")] * 2
        )
        prof = aggregate_profile(records)
        cell_stats = prof["m1"]["A"]
        assert cell_stats["pass"] == 0.6
        assert cell_stats["success"] == 3
        assert cell_stats["total"] == 5
        assert cell_stats["failure_modes"]["xml_tool_leakage"] == 1.0

    def test_avg_duration_and_iterations(self):
        records = [
            _record("A", "m1", success=True, elapsed=10.0),
            _record("A", "m1", success=True, elapsed=20.0),
        ]
        prof = aggregate_profile(records)
        assert prof["m1"]["A"]["avg_duration"] == 15.0

    def test_failure_modes_rates_over_failed_population(self):
        # 4 fails: 1 leakage, 3 mismatch. Leakage rate = 0.25 (over fails).
        records = [
            _record("B", "m", success=False, fc="xml_tool_leakage"),
            _record("B", "m", success=False, fc="verification_mismatch"),
            _record("B", "m", success=False, fc="verification_mismatch"),
            _record("B", "m", success=False, fc="verification_mismatch"),
            _record("B", "m", success=True),  # 1 success → pass=0.2
        ]
        prof = aggregate_profile(records)
        fm = prof["m"]["B"]["failure_modes"]
        assert fm["xml_tool_leakage"] == 0.25
        assert fm["verification_mismatch"] == 0.75
        assert prof["m"]["B"]["pass"] == 0.2


# ---------------------------------------------------------------------------
# Routing table derivation (A7)
# ---------------------------------------------------------------------------

class TestDeriveRoutingTable:
    def _profile(self):
        return {
            "small":  {"A": {"pass": 0.9, "total": 10, "success": 9,
                              "failure_modes": {}, "avg_duration": 5.0,
                              "avg_iterations": 1.0}},
            "medium": {"A": {"pass": 1.0, "total": 10, "success": 10,
                              "failure_modes": {}, "avg_duration": 4.0,
                              "avg_iterations": 1.0}},
            "leaky":  {"A": {"pass": 0.9, "total": 10, "success": 9,
                              "failure_modes": {"xml_tool_leakage": 0.5},
                              "avg_duration": 6.0, "avg_iterations": 2.0}},
        }

    def test_cheapest_qualified_wins(self):
        out = derive_routing_table(
            self._profile(), candidate_order=["small", "medium", "leaky"],
        )
        assert out["A"] == "small"

    def test_leaky_is_disqualified(self):
        out = derive_routing_table(
            self._profile(), candidate_order=["leaky", "medium", "small"],
        )
        # leaky is DQ'd at A; medium is the next qualified.
        assert out["A"] == "medium"
        assert "leaky" in out["_cell_decisions"]["A"]["disqualified"]

    def test_levels_table_mirrors_cells(self):
        out = derive_routing_table(
            self._profile(), candidate_order=["small", "medium", "leaky"],
        )
        # A → L1_single_call
        assert out["levels"]["L1_single_call"] == "small"

    def test_no_qualified_model_yields_empty_string(self):
        prof = {"x": {"A": {"pass": 0.3, "total": 10, "success": 3,
                            "failure_modes": {}, "avg_duration": 1.0,
                            "avg_iterations": 1.0}}}
        out = derive_routing_table(prof, candidate_order=["x"])
        assert out["A"] == ""  # empty means "fall back to default"


# ---------------------------------------------------------------------------
# TaskRouter with A7 profile consumption
# ---------------------------------------------------------------------------

class TestTaskRouterA7:
    """End-to-end: a v2 profile drives the router's disqualify/budget rules."""

    def _profile_v2(self, *, pass_rate=0.9, fm=None):
        return {
            "small": {
                "A": {"pass": pass_rate, "total": 10, "success": int(10 * pass_rate),
                      "failure_modes": fm or {}, "avg_duration": 5.0,
                      "avg_iterations": 1.0},
            },
        }

    def test_leakage_rate_at_threshold_disqualifies_model(self):
        # 0.20 is the disqualification threshold — exactly at it must trigger.
        router = TaskRouter(
            routing_table={"A": "small"},
            capability_profile=self._profile_v2(
                pass_rate=0.9, fm={"xml_tool_leakage": 0.20},
            ),
        )
        res = router.classify_and_route("What is X?", "role", ["read_file"])
        assert res["cell"] == "A"
        # small is the only candidate — DQ'd; falls through to empty string.
        assert res["model_id"] == ""
        assert "small" in res.get("disqualified", [])

    def test_slow_but_capable_gets_budget_hint_raise(self):
        # Pass rate clears threshold, slow rate >= 0.5 → budget_hint.
        router = TaskRouter(
            routing_table={"A": "small"},
            capability_profile=self._profile_v2(
                pass_rate=0.9, fm={"final_answer_slow": 0.6},
            ),
        )
        res = router.classify_and_route("What is X?", "role", ["read_file"])
        assert res["model_id"] == "small"   # not disqualified
        assert res["budget_hint"] == "raise"
        assert "budget_hint=raise" in res["explain"]

    def test_clean_profile_no_hint_no_disqualify(self):
        router = TaskRouter(
            routing_table={"A": "small"},
            capability_profile=self._profile_v2(pass_rate=0.95, fm={}),
        )
        res = router.classify_and_route("What is X?", "role", ["read_file"])
        assert res["model_id"] == "small"
        assert "budget_hint" not in res
        assert "disqualified" not in res
        assert res["confidence"] == 0.95

    def test_low_pass_rate_no_hint(self):
        # Below 0.80 threshold: budget_hint should NOT fire even with slow.
        router = TaskRouter(
            routing_table={"A": "small"},
            capability_profile=self._profile_v2(
                pass_rate=0.6, fm={"final_answer_slow": 0.8},
            ),
        )
        res = router.classify_and_route("What is X?", "role", ["read_file"])
        assert "budget_hint" not in res  # only fires when pass clears threshold

    def test_disqualify_falls_back_to_next_qualified_model(self):
        # Two candidates appear in the routing table (cell-keyed) at A:
        # leaky is picked first by table, gets DQ'd, fallback walks to clean.
        profile = {
            "leaky":  {"A": {"pass": 0.9, "total": 10, "success": 9,
                              "failure_modes": {"xml_tool_leakage": 0.5},
                              "avg_duration": 5.0, "avg_iterations": 2.0}},
            "clean":  {"A": {"pass": 0.95, "total": 10, "success": 9,
                              "failure_modes": {}, "avg_duration": 5.0,
                              "avg_iterations": 1.0}},
        }
        # Walk order: A picks leaky first (table order), B picks clean.
        # The fallback walker iterates candidates in table order; leaky is
        # first, so it gets skipped and clean is tried — which passes.
        router = TaskRouter(
            routing_table={"A": "leaky", "B": "clean"},
            capability_profile=profile,
        )
        res = router.classify_and_route("Lookup something", "role", ["read_file"])
        assert res["cell"] == "A"
        # leaky was the table's pick but DQ'd; clean is the fallback.
        assert res["model_id"] == "clean"
        assert "leaky" in res.get("disqualified", [])


# ---------------------------------------------------------------------------
# Backwards compat — old scalar schema still loads
# ---------------------------------------------------------------------------

class TestLegacyProfileBackcompat:
    def test_from_legacy_summary_emits_v2_shape(self):
        legacy = {
            "profile": {
                "m1": {"A": {"success_rate": 0.8, "total": 5, "success": 4}},
                "m2": {"B": {"success_rate": 0.6, "total": 5, "success": 3}},
            },
        }
        migrated = from_legacy_summary(legacy)
        assert migrated["m1"]["A"]["pass"] == 0.8
        assert migrated["m1"]["A"]["failure_modes"] == {}
        assert migrated["m1"]["A"]["_legacy_migrated"] is True

    def test_load_profile_detects_v2_vs_legacy(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cap.json"
            # legacy shape
            p.write_text(json.dumps({"profile": {"m": {"A": {"success_rate": 0.5}}}}))
            loaded = load_profile(p)
            assert "failure_modes" in loaded["m"]["A"]
            assert loaded["m"]["A"]["_legacy_migrated"] is True
            # v2 shape
            p.write_text(json.dumps({"m": {"A": {"pass": 0.5, "failure_modes": {}}}}))
            loaded2 = load_profile(p)
            assert "_legacy_migrated" not in loaded2["m"]["A"]
            assert loaded2["m"]["A"]["pass"] == 0.5


class TestComputeCell:
    def test_single_file_tool(self):
        assert compute_cell("What is the version?", ["read_file"]) == "A"

    def test_file_plus_write(self):
        # write_file is HIGH_AC (adds breadth) and state tool (adds depth) → D
        assert compute_cell("Read and write the result", ["read_file", "write_file"]) == "D"

    def test_multiple_independent_tools(self):
        assert compute_cell("Get info from multiple sources", ["read_file", "list_files", "web_search"]) == "C"

    def test_multi_tool_with_dependency(self):
        assert compute_cell("Read config then write result based on findings", ["read_file", "write_file", "bash_exec"]) == "D"

    def test_empty_tools(self):
        assert compute_cell("Simple question", []) == "A"

    def test_single_code_tool(self):
        # bash_exec is HIGH_AC (adds breadth) and state tool (adds depth) → D
        assert compute_cell("Run a command", ["bash_exec"]) == "D"


class TestTaskRouter:
    def test_classify_and_route(self):
        router = TaskRouter(routing_table={
            "A": "model_a",
            "B": "model_b",
            "C": "model_c",
            "D": "model_d",
        })
        result = router.classify_and_route(
            goal="What is the version?",
            role_id="test",
            declared_tools=["read_file"],
        )
        assert result["cell"] == "A"
        assert result["model_id"] == "model_a"
        assert "confidence" in result
        assert "explain" in result

    def test_cell_to_level_mapping(self):
        """Each cell maps to the demanded v2 capability level."""
        router = TaskRouter(routing_table={"A": "ma", "B": "mb", "C": "mc", "D": "md"})
        cases = [
            ("A", "L1_single_call", "What is the version?", ["read_file"]),
            ("B", "L2_multi_step", "read the value then summarize it", ["read_file"]),
            ("C", "L2_multi_step", "Get info from multiple sources",
             ["read_file", "list_files", "web_search"]),
            ("D", "L3_feedback", "Read and write based on findings",
             ["read_file", "write_file"]),
        ]
        for cell, expected_level, goal, tools in cases:
            res = router.classify_and_route(goal, "t", tools)
            assert res["cell"] == cell, f"cell {cell}: got {res['cell']}"
            assert res["level"] == expected_level, f"cell {cell}: level {res['level']}"

    def test_dispatch_subtask_forces_l4(self):
        """dispatch_subtask in declared_tools overrides to L4_orchestration."""
        router = TaskRouter(routing_table={"A": "ma", "B": "mb", "C": "mc", "D": "md"})
        res = router.classify_and_route(
            "Coordinate the work", "t", ["dispatch_subtask", "read_file"]
        )
        assert res["level"] == "L4_orchestration"
        assert "L4 override" in res["explain"]

    def test_level_keyed_table_preferred_over_cell_keyed(self):
        """A 'levels' sub-table (new format) takes precedence over cell-keyed lookup."""
        router = TaskRouter(routing_table={
            "levels": {"L1_single_call": "LEVEL_MODEL", "L4_orchestration": "L4_MODEL"},
            "A": "CELL_MODEL", "D": "CELL_D",
        })
        a = router.classify_and_route("What is the version?", "t", ["read_file"])
        assert a["model_id"] == "LEVEL_MODEL"  # level lookup, not cell A's CELL_MODEL
        l4 = router.classify_and_route("dispatch", "t", ["dispatch_subtask"])
        assert l4["model_id"] == "L4_MODEL"    # L4 override resolved via levels table

    def test_validate_tool_call_valid(self):
        router = TaskRouter(routing_table={})
        valid, reason = router.validate_tool_call(
            {"function": {"name": "read_file"}},
            ["read_file", "write_file"],
        )
        assert valid is True

    def test_validate_tool_call_invalid(self):
        router = TaskRouter(routing_table={})
        valid, reason = router.validate_tool_call(
            {"function": {"name": "bash_exec"}},
            ["read_file", "write_file"],
        )
        assert valid is False
        assert "not in role" in reason

    def test_should_escalate_loop(self):
        router = TaskRouter(routing_table={})
        trace = [
            {"tool_name": "read_file", "args": {"path": "/test"}},
            {"tool_name": "read_file", "args": {"path": "/test"}},
        ]
        escalate, reason = router.should_escalate(trace)
        assert escalate is True
        assert "Loop" in reason

    def test_should_escalate_errors(self):
        router = TaskRouter(routing_table={})
        trace = [
            {"tool_name": "read_file", "error": "not found"},
            {"tool_name": "read_file", "error": "not found"},
            {"tool_name": "read_file", "error": "not found"},
        ]
        escalate, reason = router.should_escalate(trace)
        assert escalate is True

    def test_should_not_escalate_normal(self):
        router = TaskRouter(routing_table={})
        trace = [
            {"tool_name": "read_file", "args": {"path": "/a"}},
            {"tool_name": "write_file", "args": {"path": "/b"}},
        ]
        escalate, reason = router.should_escalate(trace)
        assert escalate is False
