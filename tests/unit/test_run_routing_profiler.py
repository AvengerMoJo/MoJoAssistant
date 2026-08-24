"""Unit tests for the routing profiler (A9).

Covers the deterministic parts of run_routing_profiler:
  - CELL_BUDGETS values match the design-doc per-level priors
  - filter_models substring match
  - clean_scratch_for_task deletes the right files
  - build_tool_schema emits valid OpenAI-shape tool schemas
  - check_answer honors exact / contains / structural
  - _find_resumable_run and _find_all_done_run match by filter set
  - classify_failure integration via the per-task result
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Run from repo root so the profiler import path works.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "benchmarks"))

import run_routing_profiler as rrp  # noqa: E402
from run_routing_profiler import (
    CELL_BUDGETS,
    DEFAULT_MODELS,
    PROJECT_ROOT,
    SCRATCH_DIR,
    build_system_prompt,
    build_tool_schema,
    check_answer,
    clean_scratch_for_task,
    filter_models,
    run_task_with_model,
    validate_models_loaded,
    _effective_max_duration_s,
    _extract_scratch_target,
    _find_all_done_run,
    _find_resumable_run,
    _lms_ps_loaded_model_keys,
)


class TestBuildSystemPromptNoTruncation(unittest.TestCase):
    """Bug found live 2026-08-15: injected file/role content used to be
    hard-truncated to [:2000] chars, even though every model in the pool
    has a 262144-token (~1M+ char) context window. resource_pool.json is
    ~12KB -- truncation silently dropped everything past `gemini_elmntri`,
    so any cell-A/C task asking about a later entry (e.g.
    lmstudio_qwen36_27b_mtp) never had the answer in context at all,
    despite being designed as a "single read_file lookup, low breadth"
    task. Affected 10/15 cell-A and most resource_pool.json-based cell-C
    tasks, across all 34 historical profiler runs."""

    def test_large_file_content_not_truncated(self):
        with tempfile.TemporaryDirectory() as td:
            big_file = Path(td) / "big.json"
            # Bigger than the old 2000-char cap.
            content = "X" * 5000 + "NEEDLE_AT_END"
            big_file.write_text(content)
            task = {"setup": f"file={big_file}"}
            prompt = build_system_prompt(task)
            self.assertIn("NEEDLE_AT_END", prompt)

    def test_large_role_content_not_truncated(self):
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / ".memory" / "roles"
            roles_dir.mkdir(parents=True)
            role_file = roles_dir / "bigrole.json"
            content = "X" * 5000 + "NEEDLE_AT_END"
            role_file.write_text(content)
            task = {"setup": "role=bigrole"}
            with patch("run_routing_profiler.Path.home", return_value=Path(td)):
                prompt = build_system_prompt(task)
            self.assertIn("NEEDLE_AT_END", prompt)


class TestBuildSystemPromptRolesSetup(unittest.TestCase):
    """Bug found live 2026-08-16 on cellC_005: the setup="roles" summary
    only ever included id+capabilities. Tasks asking about executor/
    agent_type/nine_chapter_score/max_iterations had none of that in
    context, and since roles are stored one-per-file (not a single
    combined roles.json), the model burned its whole budget guessing
    nonexistent combined-file paths and never found a real answer."""

    def _make_roles_dir(self, td):
        roles_dir = Path(td) / ".memory" / "roles"
        roles_dir.mkdir(parents=True)
        (roles_dir / "popo.json").write_text(json.dumps({
            "id": "popo", "capabilities": ["exec"], "executor": "coding_agent",
            "agent_type": "executor", "nine_chapter_score": 90, "max_iterations": 20,
        }))
        (roles_dir / "paul.json").write_text(json.dumps({
            "id": "paul", "capabilities": ["orchestration"],
            "agent_type": "orchestrator",
        }))
        return roles_dir

    def test_roles_summary_includes_executor_field(self):
        with tempfile.TemporaryDirectory() as td:
            self._make_roles_dir(td)
            with patch("run_routing_profiler.Path.home", return_value=Path(td)):
                prompt = build_system_prompt({"setup": "roles"})
            self.assertIn("executor=coding_agent", prompt)
            self.assertIn("agent_type=executor", prompt)

    def test_roles_summary_notes_individual_file_path_pattern(self):
        with tempfile.TemporaryDirectory() as td:
            self._make_roles_dir(td)
            with patch("run_routing_profiler.Path.home", return_value=Path(td)):
                prompt = build_system_prompt({"setup": "roles"})
            self.assertIn("~/.memory/roles/<id>.json", prompt)

    def test_roles_summary_not_capped_at_20(self):
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / ".memory" / "roles"
            roles_dir.mkdir(parents=True)
            for i in range(25):
                (roles_dir / f"role{i}.json").write_text(json.dumps({"id": f"role{i}"}))
            with patch("run_routing_profiler.Path.home", return_value=Path(td)):
                prompt = build_system_prompt({"setup": "roles"})
            for i in range(25):
                self.assertIn(f"role{i}:", prompt)


class TestBuildSystemPromptDirSetup(unittest.TestCase):
    """Bug found live 2026-08-16: build_system_prompt() had no handler at
    all for setup="dir=..." (cellC_004, cellC_014, cellD_015) -- those
    tasks got only the bare base prompt, zero grounding. Confirmed live:
    a model burned its entire budget on `pwd`, `find / -maxdepth 3 -type d
    -name config`, and scanning unrelated project directories before ever
    reaching the actual question, because it had no idea where "config/"
    even was relative to its sandboxed bash_exec cwd."""

    def test_dir_setup_injects_directory_listing(self):
        with tempfile.TemporaryDirectory() as td:
            target_dir = Path(td) / "myconfig"
            target_dir.mkdir()
            (target_dir / "a.json").write_text("{}")
            (target_dir / "b.json").write_text("{}")
            task = {"setup": f"dir={target_dir}"}
            prompt = build_system_prompt(task)
            self.assertIn(str(target_dir), prompt)
            self.assertIn("a.json", prompt)
            self.assertIn("b.json", prompt)

    def test_dir_setup_was_previously_silent(self):
        # Documents the pre-fix behavior directly: unhandled setup prefixes
        # fell through to the bare base prompt with zero information.
        task = {"setup": "dir=config"}
        base_only = "You are a helpful assistant. Answer concisely and accurately."
        # Without a dir= branch, build_system_prompt would return exactly
        # this and nothing else -- the bug this test guards against.
        self.assertNotEqual(build_system_prompt(task), base_only)


class TestCellBudgets:
    """Cell iteration budgets (A9 fix to spec's broken max_iterations=1)."""

    def test_a_budget_matches_l1_prior(self):
        # design doc: L1=4 → cell A → L1
        assert CELL_BUDGETS["A"] == 4

    def test_b_c_budget_matches_l2_prior(self):
        # design doc: L2=8 → cells B/C → L2
        assert CELL_BUDGETS["B"] == 8
        assert CELL_BUDGETS["C"] == 8

    def test_d_budget_matches_l3_prior(self):
        # design doc: L3=12 → cell D → L3
        assert CELL_BUDGETS["D"] == 12


class TestEffectiveMaxDurationS:
    """Bug found live 2026-08-17: max_duration_s was a flat value applied
    identically to every cell regardless of its own iteration budget. Cell
    D's 12-iteration budget needs far more real wall-clock time than the
    300s default at observed per-call latency (a model scoring 100% on
    cells A-C needed 27-66s/call on cell D) -- the flat cap was cutting
    genuinely-progressing tasks off mid-budget, which was very likely the
    dominant reason cell D scored near-0% across every model profiled."""

    def test_cell_d_gets_a_much_higher_floor_than_the_default(self):
        result = _effective_max_duration_s("D", 300.0)
        assert result == 12 * 75.0  # 900s, far above the flat 300s default

    def test_cell_a_default_is_unaffected(self):
        # Budget 4 * 75s = 300s -- exactly the existing default, no change
        # in practice for a cell that's never needed more than 1-2 calls.
        result = _effective_max_duration_s("A", 300.0)
        assert result == 300.0

    def test_explicit_override_higher_than_floor_is_respected(self):
        # A caller-requested value larger than the budget-derived floor
        # must never be shrunk.
        result = _effective_max_duration_s("A", 5000.0)
        assert result == 5000.0

    def test_explicit_override_lower_than_floor_is_not_shrunk_below_floor(self):
        # The floor is a MINIMUM, not a replacement -- a low override for
        # cell D still gets at least the budget-derived floor so genuine
        # progress isn't cut off.
        result = _effective_max_duration_s("D", 60.0)
        assert result == 12 * 75.0

    def test_default_models_use_current_resource_ids(self):
        # No stale IDs from before the 2026-07-01 resource-pool cleanup.
        assert "lmstudio__google_gemma_4_26b_a4b" not in DEFAULT_MODELS  # double underscore
        assert "lmstudio_qwen36_mtp" not in DEFAULT_MODELS  # renamed
        # ornith is current priority-1.
        assert "lmstudio_ornith_35b_mtp_apex" in DEFAULT_MODELS


class TestFilterModels:
    def test_no_filter_returns_all(self):
        all_models = ["lmstudio_a", "lmstudio_b", "lmstudio_c"]
        assert filter_models(all_models, None) == all_models

    def test_substring_filter(self):
        all_models = ["lmstudio_a", "openrouter_x", "lmstudio_b"]
        assert filter_models(all_models, "lmstudio") == ["lmstudio_a", "lmstudio_b"]

    def test_empty_filter_returns_all(self):
        all_models = ["a", "b"]
        assert filter_models(all_models, "") == all_models


class TestCheckAnswer:
    def test_contains_match_case_insensitive(self):
        task = {"match_type": "contains", "correct_answer": "Qwen"}
        assert check_answer("The model is Qwen3.6", task) is True

    def test_contains_no_match(self):
        task = {"match_type": "contains", "correct_answer": "Qwen"}
        assert check_answer("The model is Gemma", task) is False

    def test_exact_match(self):
        task = {"match_type": "exact", "correct_answer": "qwen3.6-27b-mtp"}
        assert check_answer("qwen3.6-27b-mtp", task) is True
        assert check_answer("qwen3.6-27b-mtp ", task) is True  # trim
        assert check_answer("model: qwen3.6-27b-mtp", task) is False  # extra content

    def test_exact_match_numeric_tolerance(self):
        # Bug found live 2026-08-17 on cellD_015 ("count total lines"):
        # `wc -l` (what a model naturally uses via bash_exec) and Python's
        # splitlines() (what dynamic_answers.py uses) disagree by one line
        # per file lacking a trailing newline -- a real, defensible
        # ambiguity in "line count" method, not a wrong answer.
        task = {"match_type": "exact", "correct_answer": "6417", "numeric_tolerance": 10}
        assert check_answer("6413", task) is True  # within tolerance
        assert check_answer("6417", task) is True  # exact still works
        assert check_answer("5000", task) is False  # genuinely wrong, still fails

    def test_exact_match_without_tolerance_field_unaffected(self):
        # No numeric_tolerance -> identical strict behavior to before.
        task = {"match_type": "exact", "correct_answer": "6417"}
        assert check_answer("6413", task) is False

    def test_exact_match_tolerance_ignores_non_numeric_answers(self):
        # Tolerance only applies when both sides parse as numbers -- a
        # non-numeric exact-match task with a (meaningless) tolerance
        # field must not start fuzzy-matching text.
        task = {"match_type": "exact", "correct_answer": "coding_agent", "numeric_tolerance": 10}
        assert check_answer("coding_agent", task) is True
        assert check_answer("other_agent", task) is False

    def test_structural_needs_substantive_response(self):
        task = {"match_type": "structural", "correct_answer": ""}
        assert check_answer("Some meaningful answer with words", task) is True
        assert check_answer("ok", task) is False  # too short
        assert check_answer("", task) is False

    def test_empty_correct_answer_with_contains_fails(self):
        # Defensive: a non-structural task with empty correct_answer should
        # not match anything (otherwise the profiler would silently pass).
        task = {"match_type": "contains", "correct_answer": ""}
        assert check_answer("any response", task) is False

    def test_list_answer_matches_bullet_formatting(self):
        # Incident 2026-07-19: a model that lists every correct item as a
        # bullet/numbered list shouldn't fail just because it didn't
        # reproduce the literal "a,b,c" joined string.
        task = {"match_type": "contains", "correct_answer": "ahman,anna,bao"}
        response = "Roles with the capability:\n1. ahman\n2. anna\n3. bao\n"
        assert check_answer(response, task) is True

    def test_list_answer_still_fails_on_missing_item(self):
        # Tolerating format must not tolerate a genuinely incomplete list —
        # confirmed live: qwen36_31b_a3b_mtp dropped 6 of 23 real files on
        # cellC_004 and correctly still failed under this same logic.
        task = {"match_type": "contains", "correct_answer": "ahman,anna,bao"}
        response = "Roles with the capability:\n1. ahman\n2. anna\n"  # missing bao
        assert check_answer(response, task) is False

    def test_single_value_contains_unaffected_by_list_logic(self):
        # No comma in correct_answer -> falls through to plain substring,
        # unchanged from before.
        task = {"match_type": "contains", "correct_answer": "popo=263"}
        assert check_answer("popo=263 is the count", task) is True
        assert check_answer("something else", task) is False

    def test_structural_with_correct_answer_checks_value_not_length(self):
        # Incident 2026-07-19, cellB_002: match_type="structural" but the
        # task DOES carry a real correct_answer ("36"). A short-but-exact
        # value must not fail the length>10 heuristic just because it's
        # short — all 4 remaining local models wrote "36" (2 chars) to the
        # scratch file and were wrongly failed before this fix.
        task = {"match_type": "structural", "correct_answer": "36"}
        assert check_answer("36", task) is True
        assert check_answer("The count is 36.", task) is True
        assert check_answer("35", task) is False  # wrong value, still short

    def test_structural_without_correct_answer_falls_back_to_length(self):
        # Genuine structural tasks (no fixed answer) keep the original
        # "wrote something substantive" bar.
        task = {"match_type": "structural", "correct_answer": ""}
        assert check_answer("Some meaningful answer with words", task) is True
        assert check_answer("ok", task) is False

    def test_semicolon_only_answer_is_winnable_out_of_order(self):
        # Bug found live 2026-08-15: 12 real tasks (7/15 cell C, 5/15 cell
        # D) use ";" as the top-level item separator with no "," anywhere
        # in the answer key. Before the fix, only "," triggered per-item
        # splitting, so these fell through to a whole-blob substring check
        # requiring the model to reproduce the ENTIRE semicolon-joined
        # answer key verbatim, in that exact order, as one contiguous
        # string -- unwinnable by any model regardless of correctness or
        # phrasing. This directly explains why cell D scored ~0% across
        # every model ever profiled with this tool.
        #
        # The fix restores per-item independence (matching the existing
        # comma-list precedent below): each "id=value" item is checked on
        # its own, in any order, anywhere in the response. It does NOT
        # loosen the literal "id=value" substring requirement itself --
        # that stricter formatting expectation already existed for
        # comma-separated answers before this fix (see
        # test_single_value_contains_unaffected_by_list_logic) and is out
        # of scope here; this fix is specifically about the separator bug.
        task = {
            "match_type": "contains",
            "correct_answer": "gemini_avengermojo=enabled;gemini_elmntri=enabled",
        }
        # Items present, but in reverse order and with prose around them --
        # the old whole-blob check required the exact joined order.
        response = "Status: gemini_elmntri=enabled. Also, gemini_avengermojo=enabled."
        assert check_answer(response, task) is True

    def test_semicolon_only_answer_still_fails_on_missing_item(self):
        task = {
            "match_type": "contains",
            "correct_answer": "gemini_avengermojo=enabled;gemini_elmntri=enabled",
        }
        response = "gemini_avengermojo=enabled."  # missing gemini_elmntri
        assert check_answer(response, task) is False

    def test_semicolon_only_answer_unwinnable_before_fix(self):
        # Documents the pre-fix bug directly: without per-item splitting,
        # even a response containing every correct fact fails unless it
        # reproduces the entire answer key as one literal substring.
        correct = "gemini_avengermojo=enabled;gemini_elmntri=enabled"
        response_with_every_fact_but_reordered = (
            "gemini_elmntri=enabled and gemini_avengermojo=enabled"
        )
        # The old behavior (no ";" splitting): whole-blob substring check.
        assert correct.lower() not in response_with_every_fact_but_reordered.lower()

    def test_mixed_comma_and_semicolon_answer_checks_every_atomic_token(self):
        # Tasks like cellD_007 ("count=3;models=a,b,c") mix both
        # separators: ";" between top-level entities, "," inside a value
        # list. The fix flattens recursively so every atomic token --
        # including ones nested inside a comma list -- is checked
        # independently, in any order.
        task = {
            "match_type": "contains",
            "correct_answer": "count=3;models=gemini-2.5-pro,gemini-2.5-flash,gemini-2.5-flash-lite",
        }
        response = (
            "models=gemini-2.5-flash-lite models=gemini-2.5-flash "
            "models=gemini-2.5-pro count=3"
        )
        assert check_answer(response, task) is True
        # Drop one nested item -> must still fail.
        response_missing = "models=gemini-2.5-pro models=gemini-2.5-flash count=3"
        assert check_answer(response_missing, task) is False

    def test_pure_comma_answer_unaffected_by_semicolon_fix(self):
        # No ";" anywhere -> identical behavior to before.
        task = {"match_type": "contains", "correct_answer": "ahman,anna,bao"}
        response = "Roles: ahman, anna, bao"
        assert check_answer(response, task) is True

    def test_none_token_tolerates_natural_phrasing(self):
        # Bug found live 2026-08-16 on cellC_005: a model that correctly
        # said a field is absent ("not present") rather than reproducing
        # the literal Python token "=None" used to fail even though the
        # content was fully correct.
        task = {
            "match_type": "contains",
            "correct_answer": "popo=coding_agent,paul=None,rebecca=None,carl=None",
        }
        response = (
            "popo=coding_agent. paul: not present. rebecca: not present. "
            "carl: not present."
        )
        assert check_answer(response, task) is True

    def test_none_token_still_requires_the_key_present(self):
        task = {
            "match_type": "contains",
            "correct_answer": "popo=coding_agent,paul=None",
        }
        # "not present" appears but "paul" is never mentioned at all.
        response = "popo=coding_agent. Something is not present somewhere."
        assert check_answer(response, task) is False

    def test_none_token_literal_still_works(self):
        # Backward compat: the exact literal token must still pass.
        task = {"match_type": "contains", "correct_answer": "paul=None"}
        assert check_answer("paul=None", task) is True

    def test_non_none_value_unaffected_by_synonym_tolerance(self):
        # The synonym tolerance only applies when the value is literally
        # "none" -- a real value still requires its own literal substring.
        task = {"match_type": "contains", "correct_answer": "popo=coding_agent"}
        response = "popo is not present anywhere."  # wrong value, has a synonym word
        assert check_answer(response, task) is False

    def test_real_value_glued_token_brittleness_fixed(self):
        # Bug found live 2026-08-16 re-verifying the None-tolerance fix
        # above: the SAME glued-token brittleness also hits real values,
        # not just "None". qwen36_31b_a3b_mtp wrote `popo: "coding_agent"`
        # (colon+quotes) for a multi-item answer and failed despite being
        # completely correct -- no model naturally writes Python
        # dict-literal syntax in prose.
        task = {
            "match_type": "contains",
            "correct_answer": "popo=coding_agent,paul=None",
        }
        response = 'popo: "coding_agent". paul: not set.'
        assert check_answer(response, task) is True

    def test_real_value_still_requires_both_key_and_value_present(self):
        task = {"match_type": "contains", "correct_answer": "popo=coding_agent,paul=None"}
        response = 'popo: "coding_agent". '  # paul never mentioned at all
        assert check_answer(response, task) is False

    def test_short_numeric_values_do_not_use_independent_fallback(self):
        # Guard against false positives: a multi-item priority list like
        # "id_a=4,id_b=5,id_c=6" must not let id_a's check pass just
        # because SOME OTHER item's correct "5" or "6" appears elsewhere
        # in the response for a different id. Short/numeric values still
        # require the glued "key=value" substring.
        task = {"match_type": "contains", "correct_answer": "id_a=4,id_b=5"}
        # id_a is paired with the WRONG value (5, which belongs to id_b),
        # but "5" does appear somewhere in the response (for id_b) -- must
        # still fail because "id_a=4" the glued token is absent and "4" is
        # numeric so no independent fallback applies.
        response = "id_a=5, id_b=5"
        assert check_answer(response, task) is False

    def test_single_numeric_fact_uses_independent_fallback(self):
        # Bug found live 2026-08-17 re-verifying cell D: cellD_009's
        # answer "count=7;tools=..." has only ONE numeric item -- nothing
        # else it could collide with -- but the blanket numeric guard
        # blocked it anyway, failing a response that correctly wrote
        # "Total count: 7" instead of the literal "count=7".
        task = {
            "match_type": "contains",
            "correct_answer": "count=7,tools=bash_exec",
        }
        response = "Total count: 7. tools=bash_exec listed below."
        assert check_answer(response, task) is True

    def test_multiple_numeric_facts_still_require_glued_token(self):
        # Companion to the above: with MORE than one numeric item, the
        # collision risk is real again, so the stricter check stays.
        task = {"match_type": "contains", "correct_answer": "id_a=4,id_b=5,id_c=6"}
        response = "id_a=6, id_b=6, id_c=6"  # only id_c is actually correct
        assert check_answer(response, task) is False

    def test_correct_answer_fn_overrides_stale_static_answer(self):
        # Bug found live 2026-08-16: a frozen correct_answer for anything
        # derived from live state (resource counts, config files, role
        # data) goes stale the moment that state changes. correct_answer_fn
        # computes the expected value fresh at check time instead.
        task = {
            "match_type": "exact",
            "correct_answer": "999",  # deliberately wrong/stale
            "correct_answer_fn": "resource_pool_total_count",
        }
        with patch(
            "dynamic_answers.resolve_dynamic_answer", return_value="7"
        ):
            assert check_answer("7", task) is True
            assert check_answer("999", task) is False  # the stale value must NOT pass

    def test_correct_answer_fn_falls_back_to_static_when_unresolvable(self):
        task = {
            "match_type": "exact",
            "correct_answer": "fallback-value",
            "correct_answer_fn": "no_such_function_registered",
        }
        assert check_answer("fallback-value", task) is True


class TestCheckAnswerScratchTarget(unittest.TestCase):
    """Incident fix (2026-07-19): scratch-file tasks must verify the actual
    file the model wrote, not its chat prose — otherwise a model can pass
    by describing (or merely quoting) the right answer without ever
    producing the deliverable. See
    ~/.memory/research/routing_harness_verification_flaw_2607.md.
    """

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scratch = Path(self.tmp.name) / "cellD_001.txt"

    def test_chat_prose_alone_does_not_pass_when_scratch_target_given(self):
        # The model *said* the right thing in chat but never wrote the file.
        task = {"match_type": "contains", "correct_answer": "popo=263"}
        assert check_answer("The answer is popo=263", task, self.scratch) is False

    def test_missing_scratch_file_fails_even_with_matching_prose(self):
        task = {"match_type": "exact", "correct_answer": "42"}
        assert not self.scratch.exists()
        assert check_answer("42", task, self.scratch) is False

    def test_correct_file_content_passes_regardless_of_chat_prose(self):
        task = {"match_type": "exact", "correct_answer": "42"}
        self.scratch.write_text("42")
        # Chat prose is irrelevant once a scratch_target is given — only
        # the file's own content is checked.
        assert check_answer("I refuse to answer", task, self.scratch) is True

    def test_wrong_file_content_fails_even_if_prose_matches(self):
        task = {"match_type": "contains", "correct_answer": "popo=263"}
        self.scratch.write_text("9")
        assert check_answer("popo=263", task, self.scratch) is False

    def test_refusal_quoting_target_string_in_file_still_passes_naive_contains(self):
        # Documents a known residual limitation: "contains" matching on
        # the FILE is still naive substring matching. If a model writes a
        # refusal that happens to quote the target string to the scratch
        # file itself, it still passes. The fix closes the *feedback leak*
        # channel (the harness no longer hands the model that string) and
        # the *wrong-artifact* channel (chat prose is no longer checked);
        # it does not add semantic understanding to match_type=contains.
        task = {"match_type": "contains", "correct_answer": "popo=263"}
        self.scratch.write_text("I refuse to write popo=263 without verifying it.")
        assert check_answer("irrelevant", task, self.scratch) is True


class TestNoAnswerLeakInFeedback:
    """The retry-feedback text built in run_task_with_model must never
    contain task["correct_answer"] verbatim. This is a static check on the
    source rather than an execution test (the feedback branch lives inside
    a live LLM loop) — it fails loudly if someone reintroduces an f-string
    that interpolates `correct` into the feedback message.
    """

    def test_source_never_interpolates_correct_answer_into_feedback(self):
        src = (REPO_ROOT / "tests" / "benchmarks" / "run_routing_profiler.py").read_text()
        # The old bug: f"...'{correct}'..." inside the feedback block.
        assert "{correct}" not in src, (
            "Found 'correct' interpolated into a feedback string — this is "
            "the exact leak that let models pass by parroting the answer "
            "key back after a failed attempt. See incident doc: "
            "~/.memory/research/routing_harness_verification_flaw_2607.md"
        )


class TestExtractScratchTarget:
    def test_cell_d_goal_extracts_target(self):
        task = {"goal": "Compute it and write the count to ~/.memory/benchmarks/routing/scratch/cellD_001.txt"}
        target = _extract_scratch_target(task)
        assert target == SCRATCH_DIR / "cellD_001.txt"

    def test_cell_a_goal_has_no_target(self):
        task = {"goal": "What model does lmstudio_qwen36_27b_mtp use?"}
        assert _extract_scratch_target(task) is None


class TestBuildToolSchema:
    def test_known_tools_get_schemas(self):
        schema = build_tool_schema(["read_file", "write_file", "bash_exec"])
        names = [s["function"]["name"] for s in schema]
        assert names == ["read_file", "write_file", "bash_exec"]
        for s in schema:
            assert s["type"] == "function"
            assert "parameters" in s["function"]

    def test_unknown_tool_still_gets_a_stub(self):
        # Unknown tools still appear so the model knows they exist.
        schema = build_tool_schema(["unknown_tool"])
        assert len(schema) == 1
        assert schema[0]["function"]["name"] == "unknown_tool"
        # Empty params means model can call without args.
        assert schema[0]["function"]["parameters"]["properties"] == {}

    def test_empty_list_returns_empty(self):
        assert build_tool_schema([]) == []


class TestCleanScratch(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Patch SCRATCH_DIR for the duration of the test.
        self._patcher = patch(
            "run_routing_profiler.SCRATCH_DIR", Path(self.tmp.name)
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_deletes_named_scratch_files(self):
        # Create files the goal mentions.
        (Path(self.tmp.name) / "cellB_001.txt").write_text("stale")
        (Path(self.tmp.name) / "cellD_005.txt").write_text("stale")
        (Path(self.tmp.name) / "other.txt").write_text("keep")

        task = {
            "goal": (
                "Read the value and write it to "
                "~/.memory/benchmarks/routing/scratch/cellB_001.txt and "
                "scratch/cellD_005.txt"
            ),
        }
        removed = clean_scratch_for_task(task)
        assert removed == 2
        assert not (Path(self.tmp.name) / "cellB_001.txt").exists()
        assert not (Path(self.tmp.name) / "cellD_005.txt").exists()
        assert (Path(self.tmp.name) / "other.txt").exists()

    def test_no_match_does_not_delete_anything(self):
        (Path(self.tmp.name) / "unrelated.txt").write_text("keep")
        task = {"goal": "Just answer a question, no scratch writes."}
        removed = clean_scratch_for_task(task)
        assert removed == 0
        assert (Path(self.tmp.name) / "unrelated.txt").exists()


class TestResumeRunHelpers:
    """Resume semantics: skip already-completed (model, task) pairs."""

    def _make_run(self, run_root: Path, run_id: str, *,
                  completed, models, cell, tasks_per_cell, model_filter):
        rd = run_root / run_id
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "progress.json").write_text(json.dumps({
            "completed": completed,
            "models": models,
            "cell_filter": cell,
            "tasks_per_cell": tasks_per_cell,
            "model_filter": model_filter,
            "run_id": run_id,
        }))

    def test_resumable_run_skips_done_pair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Run with 2 tasks, 1 completed → resumable.
            self._make_run(root, "p1",
                completed=["m1|cellA_001"],
                models=["m1"], cell="A", tasks_per_cell=2,
                model_filter=None,
            )
            r = _find_resumable_run(root, ["m1"], "A", 2, None)
            assert r == "p1"

    def test_resumable_run_skips_when_all_done(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_run(root, "p1",
                completed=["m1|cellA_001", "m1|cellA_002"],
                models=["m1"], cell="A", tasks_per_cell=2,
                model_filter=None,
            )
            # _find_resumable_run returns None — there's no pending work.
            assert _find_resumable_run(root, ["m1"], "A", 2, None) is None
            # _find_all_done_run returns the run for the all-done detection.
            assert _find_all_done_run(root, ["m1"], "A", 2, None) == "p1"

    def test_resumable_run_filter_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_run(root, "p1",
                completed=["m1|cellA_001"],
                models=["m1"], cell="A", tasks_per_cell=2,
                model_filter=None,
            )
            # Same models, different cell → no match.
            assert _find_resumable_run(root, ["m1"], "B", 2, None) is None
            # Same models, different tasks_per_cell → no match.
            assert _find_resumable_run(root, ["m1"], "A", 5, None) is None
            # Different model_filter → no match.
            assert _find_resumable_run(root, ["m1"], "A", 2, "qwen") is None

    def test_resumable_run_picks_latest_with_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # p_old: all done
            self._make_run(root, "p_old",
                completed=["m1|cellA_001", "m1|cellA_002"],
                models=["m1"], cell="A", tasks_per_cell=2,
                model_filter=None,
            )
            # p_newer: one pending
            self._make_run(root, "p_newer",
                completed=["m1|cellA_001"],
                models=["m1"], cell="A", tasks_per_cell=2,
                model_filter=None,
            )
            # Even though p_old sorts first alphabetically when reversed, the
            # glob ordering in iterdir is filesystem-dependent. The function
            # should return whichever has pending work, regardless of order.
            r = _find_resumable_run(root, ["m1"], "A", 2, None)
            assert r in {"p_old", "p_newer"}
            assert r == "p_newer"  # only one with pending


class TestModuleInvocation(unittest.TestCase):
    """The module docstring documents `python -m tests.benchmarks.run_routing_profiler`
    as the way to run this tool. That form used to crash at first task execution
    with ModuleNotFoundError: profiler_tool_executor -- the module only added
    PROJECT_ROOT to sys.path, not its own directory, so the bare
    `from profiler_tool_executor import ...` inside run_task_with_model()
    resolved only when the script was run directly (which gets its own
    directory on sys.path[0] for free), not via -m (where sys.path[0] is the
    invoking cwd instead)."""

    def test_dash_m_invocation_imports_cleanly(self):
        import subprocess

        proc = subprocess.run(
            [sys.executable, "-m", "tests.benchmarks.run_routing_profiler", "--help"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Run routing profiler", proc.stdout)

    def test_dash_m_invocation_can_reach_profiler_tool_executor_import(self):
        """Directly reproduces the exact failure: run a real (short-lived)
        model filter that resolves to zero models so the process exits fast,
        but only after the module has fully loaded under -m. If the
        sys.path fix regresses, this still exercises the same import
        machinery as --help; the real proof is a subprocess import check of
        profiler_tool_executor itself from a cwd where only PROJECT_ROOT
        (not the script's own directory) is on sys.path -- i.e. exactly the
        -m invocation shape."""
        import subprocess

        code = (
            "import sys; "
            "sys.path.insert(0, '.'); "
            "import tests.benchmarks.run_routing_profiler as m; "
            "sys.path  # noqa\n"
            "from profiler_tool_executor import ProfilerExecutionContext\n"
            "print('OK')"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK", proc.stdout)


class TestRunTaskWithModelPathHint(unittest.IsolatedAsyncioTestCase):
    """Bug found live 2026-08-15 on cellB_004: a model that (reasonably)
    wants to re-verify system-prompt-injected file content via a real
    read_file call had to guess the path from the goal's bare filename,
    burning iteration/wall-clock budget on wrong guesses unrelated to its
    real capability. The fix appends the resolved path to the goal
    whenever the task's own `setup` field already tells the harness
    exactly which file is involved."""

    async def _run_and_capture_messages(self, task):
        captured = {}

        async def fake_call_async(messages, resource_config, model_override=None, tools=None):
            captured["messages"] = messages
            return {
                "choices": [{"message": {"content": "final answer", "tool_calls": None}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

        fake_client = MagicMock()
        fake_client.call_async = fake_call_async

        with patch("run_routing_profiler.load_resource", return_value={
            "base_url": "http://x", "model": "m", "api_key": "k",
        }), patch("app.llm.unified_client.UnifiedLLMClient", return_value=fake_client), \
             patch("app.llm.unified_client.UnifiedLLMClient.resolve_key", return_value="k"):
            await run_task_with_model(task, "fake_resource", budget=2, max_duration_s=30.0)

        return captured["messages"]

    async def test_file_setup_task_gets_path_hint(self):
        task = {
            "id": "t1", "cell": "B",
            "goal": "Find something in resource_pool.json and write it.",
            "correct_answer": "x", "match_type": "contains",
            "declared_tools": ["read_file", "write_file"],
            "setup": "file=~/.memory/config/resource_pool.json",
        }
        messages = await self._run_and_capture_messages(task)
        user_msg = next(m["content"] for m in messages if m["role"] == "user")
        self.assertIn("File path for read_file", user_msg)
        self.assertIn(str(Path.home() / ".memory" / "config" / "resource_pool.json"), user_msg)

    async def test_no_setup_task_gets_no_hint(self):
        task = {
            "id": "t2", "cell": "A",
            "goal": "What is 2+2?",
            "correct_answer": "4", "match_type": "contains",
            "declared_tools": [],
            "setup": "",
        }
        messages = await self._run_and_capture_messages(task)
        user_msg = next(m["content"] for m in messages if m["role"] == "user")
        self.assertEqual(user_msg, "What is 2+2?")
        self.assertNotIn("File path", user_msg)

    async def test_file_setup_without_file_tools_gets_no_hint(self):
        # setup="file=..." exists (for system-prompt injection) but the
        # task declares no read_file/write_file tool -- no hint needed.
        task = {
            "id": "t3", "cell": "A",
            "goal": "What model does X use?",
            "correct_answer": "x", "match_type": "contains",
            "declared_tools": [],
            "setup": "file=~/.memory/config/resource_pool.json",
        }
        messages = await self._run_and_capture_messages(task)
        user_msg = next(m["content"] for m in messages if m["role"] == "user")
        self.assertNotIn("File path", user_msg)

    async def test_dir_setup_task_gets_directory_path_hint(self):
        # Bug found live 2026-08-16: dir= tasks (cellC_004, cellC_014,
        # cellD_015) got no path hint at all -- combined with the missing
        # build_system_prompt() dir= handler, the model had zero
        # information about where the directory even was.
        task = {
            "id": "t4", "cell": "D",
            "goal": "Count total lines across all files in config/.",
            "correct_answer": "x", "match_type": "exact",
            "declared_tools": ["bash_exec", "read_file", "write_file"],
            "setup": "dir=config",
        }
        messages = await self._run_and_capture_messages(task)
        user_msg = next(m["content"] for m in messages if m["role"] == "user")
        self.assertIn("Directory path", user_msg)
        self.assertIn(str(PROJECT_ROOT / "config"), user_msg)


class TestRunTaskWithModelEmptyExceptionString(unittest.IsolatedAsyncioTestCase):
    """Bug found live 2026-08-23 on cellD_015/qwen3.8-27b: httpx.ReadTimeout
    (and asyncio.TimeoutError) stringify to "" -- a genuine per-call read
    timeout was rendering as "LLM call failed: " with nothing after the
    colon, which classify_failure's substring check can't recognize as a
    timeout, so it fell into the generic executor_exception bucket instead
    of TIMEOUT, hiding the real signal."""

    async def _run_and_capture_error(self, exc):
        async def fake_call_async(messages, resource_config, model_override=None, tools=None):
            raise exc

        fake_client = MagicMock()
        fake_client.call_async = fake_call_async

        task = {
            "id": "t1", "cell": "D",
            "goal": "do something", "correct_answer": "x", "match_type": "exact",
            "declared_tools": [], "setup": "",
        }
        with patch("run_routing_profiler.load_resource", return_value={
            "base_url": "http://x", "model": "m", "api_key": "k",
        }), patch("app.llm.unified_client.UnifiedLLMClient", return_value=fake_client), \
             patch("app.llm.unified_client.UnifiedLLMClient.resolve_key", return_value="k"):
            result = await run_task_with_model(task, "fake_resource", budget=2, max_duration_s=30.0)
        return result

    async def test_empty_str_exception_falls_back_to_class_name(self):
        import httpx
        result = await self._run_and_capture_error(httpx.ReadTimeout(""))
        self.assertEqual(result["error"], "LLM call failed: ReadTimeout")

    async def test_asyncio_timeout_error_falls_back_to_class_name(self):
        result = await self._run_and_capture_error(TimeoutError())
        self.assertEqual(result["error"], "LLM call failed: TimeoutError")

    async def test_exception_with_a_real_message_is_unaffected(self):
        result = await self._run_and_capture_error(ValueError("bad payload"))
        self.assertEqual(result["error"], "LLM call failed: bad payload")


class TestLmsPsLoadedModelKeys(unittest.TestCase):
    """Bug found live 2026-08-23: the profiler fired requests straight at
    resource_pool.json's base_url/model with no check that LMStudio
    actually has those weights loaded -- an unloaded model either 400s or
    JIT-loads mid-run, either way polluting results with load-state noise
    rather than measuring capability."""

    def test_returns_none_on_nonzero_exit(self):
        fake_proc = MagicMock(returncode=1, stdout="", stderr="boom")
        with patch("subprocess.run", return_value=fake_proc):
            self.assertIsNone(_lms_ps_loaded_model_keys())

    def test_returns_none_on_exception(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("no lms binary")):
            self.assertIsNone(_lms_ps_loaded_model_keys())

    def test_extracts_identifier_modelkey_and_path_fields(self):
        stdout = json.dumps([
            {"identifier": "qwen/qwen3.8-27b", "modelKey": "qwen3.8-27b-key", "path": "/models/qwen3.8"},
            {"identifier": "other-model"},
        ])
        fake_proc = MagicMock(returncode=0, stdout=stdout, stderr="")
        with patch("subprocess.run", return_value=fake_proc):
            keys = _lms_ps_loaded_model_keys()
        self.assertEqual(
            keys,
            {"qwen/qwen3.8-27b", "qwen3.8-27b-key", "/models/qwen3.8", "other-model"},
        )


class TestValidateModelsLoaded(unittest.TestCase):
    def test_drops_local_model_not_currently_loaded(self):
        with patch.object(rrp, "_lms_ps_loaded_model_keys", return_value={"qwen/qwen3.8-27b"}), \
             patch.object(rrp, "load_resource", side_effect=lambda rid: {
                 "lmstudio_loaded": {"type": "local", "model": "qwen/qwen3.8-27b"},
                 "lmstudio_unloaded": {"type": "local", "model": "gemma-4-31b-qat"},
             }[rid]):
            result = validate_models_loaded(["lmstudio_loaded", "lmstudio_unloaded"])
        self.assertEqual(result, ["lmstudio_loaded"])

    def test_api_resources_are_never_filtered_by_load_state(self):
        with patch.object(rrp, "_lms_ps_loaded_model_keys", return_value=set()), \
             patch.object(rrp, "load_resource", return_value={"type": "api", "model": "gemini-2.5-pro"}):
            result = validate_models_loaded(["gemini_avengermojo"])
        self.assertEqual(result, ["gemini_avengermojo"])

    def test_unknown_resource_id_is_dropped(self):
        with patch.object(rrp, "_lms_ps_loaded_model_keys", return_value=set()), \
             patch.object(rrp, "load_resource", return_value=None):
            result = validate_models_loaded(["no_such_resource"])
        self.assertEqual(result, [])

    def test_fails_open_when_lms_ps_unavailable(self):
        # If we can't even ask LMStudio what's loaded, don't silently drop
        # every model -- that would turn "lms isn't on PATH" into "0 models
        # tested" with no visible cause.
        with patch.object(rrp, "_lms_ps_loaded_model_keys", return_value=None):
            result = validate_models_loaded(["lmstudio_whatever"])
        self.assertEqual(result, ["lmstudio_whatever"])


if __name__ == "__main__":
    unittest.main()