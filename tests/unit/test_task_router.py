"""Tests for task router."""

import pytest
from app.scheduler.task_router import (
    compute_cell, TaskRouter, RoutingResult,
    apply_budget_hint, LEVEL_ITERATION_PRIORS,
)
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

    def test_max_duration_exceeded_string_classified_as_timeout(self):
        # Bug found live 2026-08-17: the profiler's own wall-clock cutoff
        # raises "max_duration_s exceeded (300.0s)" -- containing neither
        # "timeout" nor "timed out" -- so genuine cap-hits were falling
        # through to the generic EXECUTOR_EXCEPTION bucket. Confirmed
        # live: 6/9 "executor_exception" results in one cell-D run were
        # actually this exact cutoff.
        fc = classify_failure(
            success=False, elapsed_s=300.0,
            error="max_duration_s exceeded (300.0s)",
        )
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

    def test_slow_threshold_is_60s_not_30s(self):
        # Adjusted live 2026-08-16: the original 30s bar was disproportionate
        # to the real per-task budget (up to 300s / 8+ iterations) -- a local
        # model doing genuine tool-call reasoning in 34-37s isn't "slow" in
        # any practical sense. Raised to 60s.
        assert classify_failure(success=True, elapsed_s=45.0) is None  # under 60s -> clean
        assert classify_failure(success=True, elapsed_s=61.0) is FailureClass.FINAL_ANSWER_SLOW

    def test_timeout_threshold_matches_real_budget_cap(self):
        # Raised from 120s to 300s to match run_routing_profiler's real
        # max_duration_s cap -- see TIMEOUT_DURATION_S docstring comment.
        assert TIMEOUT_DURATION_S == 300.0

    def test_correct_slow_answer_no_longer_mislabeled_timeout(self):
        # The landmine this fixes: before, a genuinely correct answer that
        # simply took >120s (well within the real 300s allowance) got
        # labeled "timeout" even though success stayed True -- misleading
        # to anyone reading failure_modes without also checking success.
        # Now the classifier can't fire ahead of an actual timeout: by
        # 300s the run loop itself would already have cut the task off.
        fc = classify_failure(success=True, elapsed_s=150.0)
        assert fc is FailureClass.FINAL_ANSWER_SLOW  # not TIMEOUT
        assert fc is not FailureClass.TIMEOUT


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
# A11.3 — tool-execution aggregates
# ---------------------------------------------------------------------------

def _record_with_tools(cell, model, success, tool_calls=0, tool_errors=0):
    """Variant of _record that lets us set tool_call_count / tool_error_count."""
    return TaskRecord(
        task_id=f"{cell}_{model}", cell=cell, resource_id=model,
        success=success, elapsed_s=5.0,
        tool_call_count=tool_calls, tool_error_count=tool_errors,
    )


class TestToolExecutionAggregates:
    """A11.3 — tool-execution aggregates in the profile schema."""

    def test_no_tool_calls_default_to_zero(self):
        # Cell A tasks: no tools. Should still produce a valid profile.
        records = [_record("A", "m1", success=True) for _ in range(3)]
        prof = aggregate_profile(records)
        cell_stats = prof["m1"]["A"]
        assert cell_stats["avg_tool_calls"] == 0.0
        assert cell_stats["tool_error_rate"] == 0.0
        assert cell_stats["tasks_using_tools"] == 0

    def test_avg_tool_calls_across_tasks(self):
        # 3 tasks, 0+2+4 = 6 tool calls total → avg = 2.0
        records = [
            _record_with_tools("B", "m", success=True, tool_calls=0),
            _record_with_tools("B", "m", success=True, tool_calls=2),
            _record_with_tools("B", "m", success=False, tool_calls=4),
        ]
        prof = aggregate_profile(records)
        assert prof["m"]["B"]["avg_tool_calls"] == 2.0

    def test_tool_error_rate_over_call_population(self):
        # 10 total tool calls across 2 tasks; 3 had errors.
        records = [
            _record_with_tools("B", "m", success=True, tool_calls=4, tool_errors=1),
            _record_with_tools("B", "m", success=False, tool_calls=6, tool_errors=2),
        ]
        prof = aggregate_profile(records)
        assert prof["m"]["B"]["tool_error_rate"] == 0.3  # 3/10

    def test_tasks_using_tools_count(self):
        # 5 tasks: 2 used tools, 3 didn't.
        records = [
            _record_with_tools("B", "m", success=True, tool_calls=3),
            _record_with_tools("B", "m", success=True, tool_calls=0),
            _record_with_tools("B", "m", success=True, tool_calls=0),
            _record_with_tools("B", "m", success=False, tool_calls=5),
            _record_with_tools("B", "m", success=True, tool_calls=0),
        ]
        prof = aggregate_profile(records)
        assert prof["m"]["B"]["tasks_using_tools"] == 2
        assert prof["m"]["B"]["avg_tool_calls"] == 1.6  # 8/5

    def test_legacy_records_load_with_zero_tool_aggregates(self):
        """Records without tool fields (pre-A11.2) should default to 0."""
        from dataclasses import dataclass
        @dataclass
        class LegacyRecord:
            task_id: str
            cell: str
            resource_id: str
            success: bool
            elapsed_s: float = 5.0
        # aggregate_profile expects TaskRecord; verify the default
        # values exist in the dataclass itself.
        from app.scheduler.routing_profile import TaskRecord
        r = TaskRecord(task_id="x", cell="A", resource_id="m", success=True)
        assert r.tool_call_count == 0
        assert r.tool_error_count == 0
        assert r.tool_calls_log is None
        # And the aggregation handles defaults cleanly.
        prof = aggregate_profile([r])
        assert prof["m"]["A"]["avg_tool_calls"] == 0.0
        assert prof["m"]["A"]["tool_error_rate"] == 0.0


class TestLegacyMigrationWithNewFields:
    """from_legacy_summary must emit the new fields with safe defaults."""

    def test_legacy_migrated_entries_have_new_fields(self):
        from app.scheduler.routing_profile import from_legacy_summary
        legacy = {"profile": {
            "m1": {"A": {"success_rate": 0.8, "total": 5, "success": 4}},
        }}
        migrated = from_legacy_summary(legacy)
        entry = migrated["m1"]["A"]
        assert entry["avg_tool_calls"] == 0.0
        assert entry["tool_error_rate"] == 0.0
        assert entry["tasks_using_tools"] == 0
        assert entry["_legacy_migrated"] is True

    def test_derive_routing_table_ignores_tool_aggregates(self):
        """The new fields must not affect routing decisions — only
        pass + failure_modes + disqualify thresholds do."""
        from app.scheduler.routing_profile import derive_routing_table
        # Same pass rate, different tool-error rates — routing outcome identical.
        for tool_err in (0.0, 0.5, 1.0):
            profile = {
                "m1": {"A": {"pass": 0.85, "total": 10, "success": 8,
                              "failure_modes": {}, "avg_duration": 5.0,
                              "avg_iterations": 1.0,
                              "avg_tool_calls": 3.0, "tool_error_rate": tool_err,
                              "tasks_using_tools": 10}},
            }
            out = derive_routing_table(profile, candidate_order=["m1"])
            assert out["A"] == "m1"  # qualified regardless of tool errors

    def test_legacy_profile_loads_via_load_profile(self):
        """End-to-end: an old summary.json loads with the new fields defaulted."""
        import json
        import tempfile
        from pathlib import Path
        from app.scheduler.routing_profile import load_profile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cap.json"
            p.write_text(json.dumps({
                "profile": {
                    "m1": {"A": {"success_rate": 0.7, "total": 10, "success": 7}}
                }
            }))
            loaded = load_profile(p)
            assert "avg_tool_calls" in loaded["m1"]["A"]
            assert "tool_error_rate" in loaded["m1"]["A"]
            assert loaded["m1"]["A"]["_legacy_migrated"] is True


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

    # ---- A11.7 — cost-order in the routing table ----

    def test_disqualify_walks_cost_order_when_present(self):
        """_cost_order in the routing table is the single source of truth
        for fallback ordering. The cell-keyed table picks the initial
        winner; the cost-order list dictates who comes next.
        """
        profile = {
            "qwen31b": {"A": {"pass": 0.9, "total": 10, "success": 9,
                                "failure_modes": {"xml_tool_leakage": 0.5},
                                "avg_duration": 5.0, "avg_iterations": 2.0,
                                "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                                "tasks_using_tools": 0}},
            "gemma12b": {"A": {"pass": 0.95, "total": 10, "success": 9,
                                 "failure_modes": {}, "avg_duration": 5.0,
                                 "avg_iterations": 1.0,
                                 "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                                 "tasks_using_tools": 0}},
            "ornith":   {"A": {"pass": 1.0, "total": 10, "success": 10,
                                "failure_modes": {}, "avg_duration": 5.0,
                                "avg_iterations": 1.0,
                                "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                                "tasks_using_tools": 0}},
        }
        router = TaskRouter(
            routing_table={
                "A": "qwen31b",  # table pick
                "_cost_order": ["gemma12b", "qwen31b", "ornith"],  # explicit cost order
            },
            capability_profile=profile,
        )
        res = router.classify_and_route("Lookup", "role", ["read_file"])
        # qwen31b was the cell-A pick but DQ'd for leakage.
        assert "qwen31b" in res.get("disqualified", [])
        # Fallback walks _cost_order: gemma12b (cheaper) qualifies → wins.
        # Without _cost_order, the cell-keyed walk might land on a more
        # expensive model.
        assert res["model_id"] == "gemma12b"

    def test_disqualify_cost_order_prefers_cheapest_over_expensive(self):
        """Cost order beats cell-table insertion order on fallback."""
        profile = {
            "expensive_but_qualified": {
                "A": {"pass": 1.0, "total": 10, "success": 10,
                      "failure_modes": {}, "avg_duration": 5.0,
                      "avg_iterations": 1.0,
                      "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                      "tasks_using_tools": 0}
            },
            "cheap_qualified": {
                "A": {"pass": 0.85, "total": 10, "success": 9,
                      "failure_modes": {}, "avg_duration": 5.0,
                      "avg_iterations": 1.0,
                      "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                      "tasks_using_tools": 0}
            },
            "table_pick_dq": {
                "A": {"pass": 0.9, "total": 10, "success": 9,
                      "failure_modes": {"malformed_arguments": 0.5},
                      "avg_duration": 5.0, "avg_iterations": 2.0,
                      "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                      "tasks_using_tools": 0}
            },
        }
        router = TaskRouter(
            routing_table={
                "A": "table_pick_dq",  # would be picked if not DQ'd
                "B": "expensive_but_qualified",  # inserted first → would win naive walk
                "_cost_order": ["cheap_qualified", "table_pick_dq", "expensive_but_qualified"],
            },
            capability_profile=profile,
        )
        res = router.classify_and_route("Lookup", "role", ["read_file"])
        # table_pick_dq is DQ'd. _cost_order says cheap_qualified first →
        # that wins, not the cell-B entry.
        assert res["model_id"] == "cheap_qualified"

    def test_no_cost_order_falls_back_to_cell_table(self):
        """Old routing tables (no _cost_order) still work via legacy walk."""
        profile = {
            "m1": {"A": {"pass": 0.9, "total": 10, "success": 9,
                          "failure_modes": {"xml_tool_leakage": 0.5},
                          "avg_duration": 5.0, "avg_iterations": 2.0,
                          "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                          "tasks_using_tools": 0}},
            "m2": {"A": {"pass": 0.95, "total": 10, "success": 9,
                          "failure_modes": {}, "avg_duration": 5.0,
                          "avg_iterations": 1.0,
                          "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                          "tasks_using_tools": 0}},
        }
        router = TaskRouter(
            routing_table={"A": "m1", "B": "m2"},  # no _cost_order
            capability_profile=profile,
        )
        res = router.classify_and_route("Lookup", "role", ["read_file"])
        # m1 DQ'd, m2 in cell-B entry → fallback finds it via legacy walk.
        assert res["model_id"] == "m2"


# ---------------------------------------------------------------------------
# A11.7 — cost-order in derive_routing_table output
# ---------------------------------------------------------------------------

class TestDeriveRoutingTableEmitsCostOrder:
    def test_cost_order_emitted_when_provided(self):
        from app.scheduler.routing_profile import derive_routing_table
        profile = {
            "small":  {"A": {"pass": 0.9, "total": 10, "success": 9,
                              "failure_modes": {}, "avg_duration": 5.0,
                              "avg_iterations": 1.0,
                              "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                              "tasks_using_tools": 0}},
            "medium": {"A": {"pass": 1.0, "total": 10, "success": 10,
                              "failure_modes": {}, "avg_duration": 4.0,
                              "avg_iterations": 1.0,
                              "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                              "tasks_using_tools": 0}},
        }
        out = derive_routing_table(profile, candidate_order=["small", "medium"])
        assert out["_cost_order"] == ["small", "medium"]

    def test_no_cost_order_falls_back_to_sorted_keys(self):
        from app.scheduler.routing_profile import derive_routing_table
        profile = {
            "m1": {"A": {"pass": 0.9, "total": 10, "success": 9,
                          "failure_modes": {}, "avg_duration": 5.0,
                          "avg_iterations": 1.0,
                          "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                          "tasks_using_tools": 0}},
        }
        # candidate_order=None → defaults to sorted(profile.keys()).
        out = derive_routing_table(profile, candidate_order=None)
        # _cost_order is always emitted; without an explicit list it
        # falls back to the deterministic sorted-keys default.
        assert out["_cost_order"] == ["m1"]


# ---------------------------------------------------------------------------
# Post-A10 follow-up: budget_hint consumption
# ---------------------------------------------------------------------------

class TestApplyBudgetHint:
    """The v2 router's budget_hint="raise" signal bumps max_iterations.

    Per the design doc, slow-but-capable models get more rope (not
    disqualification). apply_budget_hint writes the per-level iteration
    prior into the task config so the executor picks it up.
    """

    def test_no_hint_is_noop(self):
        cfg = {"max_iterations": 6, "max_duration_seconds": 300}
        original = dict(cfg)
        routing = {"cell": "B", "level": "L2_multi_step", "model_id": "m1"}
        # No budget_hint key — apply_budget_hint must not touch the config.
        assert apply_budget_hint(routing, cfg) is cfg
        assert cfg == original

    def test_hint_raise_writes_per_level_prior(self):
        cfg = {}
        routing = {
            "cell": "B", "level": "L2_multi_step", "model_id": "m1",
            "budget_hint": "raise",
        }
        apply_budget_hint(routing, cfg)
        assert cfg["max_iterations"] == LEVEL_ITERATION_PRIORS["L2_multi_step"]
        assert cfg["max_iterations"] == 8
        # Wall-clock floor: prior * 30s.
        assert cfg["max_duration_seconds"] == 8 * 30
        # Provenance recorded.
        assert cfg["_budget_hint_source"]["level"] == "L2_multi_step"
        assert cfg["_budget_hint_source"]["prior_iterations"] == 8
        assert cfg["_budget_hint_source"]["model_id"] == "m1"

    def test_each_level_has_correct_prior(self):
        # Locks the design-doc ladder.
        cases = [
            ("L1_single_call", 4),
            ("L2_multi_step", 8),
            ("L3_feedback", 12),
            ("L4_orchestration", 25),
        ]
        for level, expected_prior in cases:
            cfg = {}
            routing = {"level": level, "model_id": "m", "budget_hint": "raise"}
            apply_budget_hint(routing, cfg)
            assert cfg["max_iterations"] == expected_prior, (
                f"level={level}: expected {expected_prior}, got {cfg.get('max_iterations')}"
            )

    def test_does_not_lower_existing_max_iterations(self):
        # Operator override: max_iterations=50 must win over the L2 prior of 8.
        cfg = {"max_iterations": 50, "max_duration_seconds": 1000}
        routing = {
            "level": "L2_multi_step", "model_id": "m",
            "budget_hint": "raise",
        }
        apply_budget_hint(routing, cfg)
        assert cfg["max_iterations"] == 50  # not lowered to 8
        assert cfg["max_duration_seconds"] == 1000  # not lowered to 240

    def test_only_raises_never_lowers(self):
        cfg = {"max_iterations": 4, "max_duration_seconds": 600}
        # L3 prior is 12. Existing iters=4 (lower) → bump to 12.
        # Existing dur=600 (higher than 12*30=360) → keep 600.
        routing = {
            "level": "L3_feedback", "model_id": "m",
            "budget_hint": "raise",
        }
        apply_budget_hint(routing, cfg)
        assert cfg["max_iterations"] == 12
        assert cfg["max_duration_seconds"] == 600

    def test_unknown_level_is_noop(self):
        # Defensive: if the level isn't in the priors table, do nothing.
        cfg = {"max_iterations": 4}
        routing = {"level": "L99_future", "model_id": "m", "budget_hint": "raise"}
        apply_budget_hint(routing, cfg)
        assert cfg == {"max_iterations": 4}
        assert "_budget_hint_source" not in cfg

    def test_hint_value_other_than_raise_is_noop(self):
        # The contract is "raise" → bump. Any other value (or absent)
        # is a no-op. Future signal values would be a separate addition.
        cfg = {}
        for hint_value in (None, "", "lower", "extend_wall_only", "unknown"):
            routing = {"level": "L1_single_call", "model_id": "m", "budget_hint": hint_value}
            apply_budget_hint(routing, cfg)
            assert "max_iterations" not in cfg, f"hint={hint_value!r} should be no-op"

    def test_idempotent(self):
        # Re-applying the same hint is a no-op (config already has the prior).
        cfg = {}
        routing = {"level": "L2_multi_step", "model_id": "m", "budget_hint": "raise"}
        apply_budget_hint(routing, cfg)
        first = dict(cfg)
        apply_budget_hint(routing, cfg)
        assert cfg == first

    def test_empty_routing_dict_is_noop(self):
        # Defensive: classify_and_route may have failed silently. The
        # handler's cfg still has the routing dict (possibly empty).
        cfg = {"max_iterations": 6}
        original = dict(cfg)
        assert apply_budget_hint({}, cfg) is cfg
        assert cfg == original


class TestClassifyAndRouteEmitsBudgetHint:
    """End-to-end: classify_and_route emits budget_hint when the model
    is slow/timeout-dominant but otherwise qualified, and the
    downstream handler can consume it via apply_budget_hint."""

    def test_budget_hint_attached_for_slow_qualified_model(self):
        # Synthetic profile: model passes threshold (0.9) but
        # failure_modes is dominated by final_answer_slow (0.6) and
        # timeout (0.4) — sum=1.0 >= SLOW_DOMINANT_RATE (0.5), pass
        # clears 0.80. This is the textbook budget_hint case.
        router = TaskRouter(
            routing_table={"A": "slow_model"},
            capability_profile={
                "slow_model": {"A": {
                    "pass": 0.9, "total": 10, "success": 9,
                    "failure_modes": {
                        "final_answer_slow": 0.6, "timeout": 0.4,
                    },
                    "avg_duration": 60.0, "avg_iterations": 5.0,
                    "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                    "tasks_using_tools": 0,
                }},
            },
        )
        res = router.classify_and_route("simple task", "role", ["read_file"])
        self._check_budget_hint_attached(res, expected_level="L1_single_call")

    def _check_budget_hint_attached(self, res, expected_level):
        assert res["budget_hint"] == "raise"
        assert res["level"] == expected_level
        assert "model_id" in res

        # The handler consumes via apply_budget_hint. Verify the
        # round-trip: routing → config with the per-level prior.
        cfg = {}
        apply_budget_hint(res, cfg)
        assert cfg["max_iterations"] == LEVEL_ITERATION_PRIORS[expected_level]

    def test_no_budget_hint_for_clean_model(self):
        # Same pass rate, but failure_modes is empty. No slow/timeout
        # dominance → no budget_hint.
        router = TaskRouter(
            routing_table={"A": "clean_model"},
            capability_profile={
                "clean_model": {"A": {
                    "pass": 0.9, "total": 10, "success": 9,
                    "failure_modes": {},
                    "avg_duration": 5.0, "avg_iterations": 1.0,
                    "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                    "tasks_using_tools": 0,
                }},
            },
        )
        res = router.classify_and_route("simple task", "role", ["read_file"])
        assert "budget_hint" not in res

    def test_no_budget_hint_when_disqualified(self):
        # High failure_modes rate → DQ, no hint. (Disqualified means
        # the model shouldn't be picked at all; the hint would
        # contradict that.)
        router = TaskRouter(
            routing_table={"A": "leaky"},
            capability_profile={
                "leaky": {"A": {
                    "pass": 0.9, "total": 10, "success": 9,
                    "failure_modes": {"xml_tool_leakage": 0.5},
                    "avg_duration": 5.0, "avg_iterations": 1.0,
                    "avg_tool_calls": 0.0, "tool_error_rate": 0.0,
                    "tasks_using_tools": 0,
                }},
            },
        )
        res = router.classify_and_route("simple task", "role", ["read_file"])
        assert "leaky" in res.get("disqualified", [])
        # budget_hint shouldn't be attached to a DQ'd model.
        assert "budget_hint" not in res


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
