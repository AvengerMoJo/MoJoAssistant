"""
Smoke — NineChapter behavioral overlay and task context generation.

Verifies:
  - build_behavioral_overlay produces correct directives from dimension scores
  - Score thresholds gate directives correctly
  - build_task_context produces success_patterns and escalation_rules blocks
  - Empty/missing fields produce empty strings (no crash)

No network or LLM calls required.
"""

import pytest
from app.scheduler.ninechapter import build_behavioral_overlay, build_task_context


_REBECCA_ROLE = {
    "name": "Rebecca",
    "dimensions": {
        "core_values": {"score": 100},
        "emotional_reaction": {"score": 100},
        "cognitive_style": {"score": 90},
        "social_orientation": {"score": 90},
        "adaptability": {"score": 85},
    },
    "success_patterns": {
        "research": "Goal covered by 2+ sources, uncertainties named, synthesis included.",
        "comparison": "Each dimension has a verdict with examples, hybrid path identified.",
    },
    "escalation_rules": {
        "escalate_when": ["Tool permanently unavailable", "Only user can decide"],
        "do_not_escalate_when": ["Search fails once — retry", "Uncertain — state it and continue"],
    },
}

_LOW_SCORE_ROLE = {
    "name": "LowScore",
    "dimensions": {
        "core_values": {"score": 50},
        "emotional_reaction": {"score": 60},
        "cognitive_style": {"score": 55},
        "social_orientation": {"score": 40},
        "adaptability": {"score": 60},
    },
}


class TestBehavioralOverlay:

    def test_empty_role_returns_empty_string(self):
        assert build_behavioral_overlay({}) == ""

    def test_no_dimensions_returns_empty_string(self):
        assert build_behavioral_overlay({"name": "Nodims"}) == ""

    def test_rebecca_produces_overlay(self):
        result = build_behavioral_overlay(_REBECCA_ROLE)
        assert len(result.strip()) > 0
        assert "## Behavioral calibration" in result

    def test_rebecca_evidence_requirement_present(self):
        result = build_behavioral_overlay(_REBECCA_ROLE)
        assert "2 independent" in result or "independent sources" in result

    def test_rebecca_response_density_present(self):
        result = build_behavioral_overlay(_REBECCA_ROLE)
        assert "density" in result.lower() or "comprehensive" in result.lower()

    def test_rebecca_assertiveness_present(self):
        result = build_behavioral_overlay(_REBECCA_ROLE)
        assert "clearly" in result.lower() or "assertive" in result.lower() or "position" in result.lower()

    def test_rebecca_escalation_threshold_present(self):
        result = build_behavioral_overlay(_REBECCA_ROLE)
        assert "escalat" in result.lower()

    def test_low_scores_produce_no_overlay(self):
        """All scores below thresholds → empty string, no crash."""
        result = build_behavioral_overlay(_LOW_SCORE_ROLE)
        assert result == ""

    def test_score_as_plain_int_works(self):
        """Dimensions stored as plain int (not dict) should also work."""
        role = {"dimensions": {"core_values": 95, "cognitive_style": 88}}
        result = build_behavioral_overlay(role)
        assert "## Behavioral calibration" in result

    def test_overlay_ends_with_double_newline(self):
        """Overlay must end with \n\n so it separates cleanly from persona."""
        result = build_behavioral_overlay(_REBECCA_ROLE)
        assert result.endswith("\n\n")


class TestTaskContext:

    def test_empty_role_returns_empty_string(self):
        assert build_task_context({}) == ""

    def test_no_success_patterns_or_escalation_returns_empty(self):
        assert build_task_context({"name": "NoPatterns"}) == ""

    def test_success_patterns_appear_in_output(self):
        result = build_task_context(_REBECCA_ROLE)
        assert "research" in result
        assert "comparison" in result
        assert "2+ sources" in result

    def test_escalation_rules_appear_in_output(self):
        result = build_task_context(_REBECCA_ROLE)
        assert "escalate" in result.lower()
        assert "Tool permanently unavailable" in result
        assert "retry" in result.lower()

    def test_escalate_when_and_do_not_both_present(self):
        result = build_task_context(_REBECCA_ROLE)
        assert "Escalate when" in result or "escalate when" in result.lower()
        assert "NOT escalate" in result or "not escalate" in result.lower()

    def test_success_patterns_only_no_crash(self):
        role = {"success_patterns": {"research": "Cover all sources."}}
        result = build_task_context(role)
        assert "research" in result
        assert "Cover all sources" in result

    def test_escalation_only_no_crash(self):
        role = {"escalation_rules": {"escalate_when": ["Only user can decide"]}}
        result = build_task_context(role)
        assert "Only user can decide" in result

    def test_task_context_ends_with_double_newline(self):
        result = build_task_context(_REBECCA_ROLE)
        assert result.endswith("\n\n")

    def test_complete_answer_header_present(self):
        result = build_task_context(_REBECCA_ROLE)
        assert "complete answer" in result.lower() or "What a complete" in result
