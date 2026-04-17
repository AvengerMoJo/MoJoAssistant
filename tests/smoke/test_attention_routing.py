"""
Smoke — Per-source attention routing rules.

Verifies that event_rules in attention_routing.json are evaluated
before source_rules, that first-match wins, and that set_level /
min_level / max_level all work correctly.

No network or LLM calls required.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from app.mcp.adapters.attention_classifier import (
    AttentionClassifier,
    _rule_matches,
    _load_event_rules,
)


# ---------------------------------------------------------------------------
# _rule_matches unit tests
# ---------------------------------------------------------------------------

class TestRuleMatches:

    def test_single_field_match(self):
        rule = {"match": {"task_type": "dreaming"}}
        event = {"task_type": "dreaming", "event_type": "task_failed"}
        assert _rule_matches(rule, event) is True

    def test_single_field_no_match(self):
        rule = {"match": {"task_type": "dreaming"}}
        event = {"task_type": "assistant", "event_type": "task_failed"}
        assert _rule_matches(rule, event) is False

    def test_multi_field_all_match(self):
        rule = {"match": {"task_type": "agent", "event_type": "task_failed"}}
        event = {"task_type": "agent", "event_type": "task_failed"}
        assert _rule_matches(rule, event) is True

    def test_multi_field_partial_match_fails(self):
        rule = {"match": {"task_type": "agent", "event_type": "task_failed"}}
        event = {"task_type": "agent", "event_type": "task_completed"}
        assert _rule_matches(rule, event) is False

    def test_empty_match_never_matches(self):
        rule = {"match": {}}
        assert _rule_matches(rule, {"task_type": "anything"}) is False

    def test_missing_match_key_never_matches(self):
        rule = {"set_level": 3}
        assert _rule_matches(rule, {"task_type": "anything"}) is False

    def test_role_id_field_matched(self):
        rule = {"match": {"task_type": "assistant", "role_id": "security_sentinel"}}
        assert _rule_matches(rule, {"task_type": "assistant", "role_id": "security_sentinel"}) is True
        assert _rule_matches(rule, {"task_type": "assistant", "role_id": "researcher"}) is False


# ---------------------------------------------------------------------------
# AttentionClassifier with mocked event_rules
# ---------------------------------------------------------------------------

def _classify_with_rules(event_rules: list, event: dict) -> int:
    """
    Classify *event* using *event_rules* (source_rules use defaults).
    Resets the module-level cache so injected rules take effect.
    """
    from app.mcp.adapters import attention_classifier as ac
    ac._SOURCE_RULES = None
    ac._EVENT_RULES = event_rules
    level = AttentionClassifier.classify(event)
    ac._SOURCE_RULES = None
    ac._EVENT_RULES = None
    return level


class TestEventRules:

    def test_set_level_overrides_base(self):
        """set_level rule replaces the computed base level."""
        rules = [{"match": {"task_type": "dreaming", "event_type": "task_failed"}, "set_level": 1}]
        # Base level for task_failed = 3; rule overrides to 1
        level = _classify_with_rules(rules, {"task_type": "dreaming", "event_type": "task_failed"})
        assert level == 1

    def test_min_level_raises_floor(self):
        """min_level rule raises the level if base is lower."""
        rules = [{"match": {"task_type": "agent", "event_type": "task_failed"}, "min_level": 3}]
        level = _classify_with_rules(rules, {"task_type": "agent", "event_type": "task_failed"})
        assert level >= 3

    def test_max_level_caps_level(self):
        """max_level rule caps the level if base is higher."""
        rules = [{"match": {"task_type": "scheduled", "event_type": "task_failed"}, "max_level": 2}]
        # task_failed → base 3; rule caps to 2
        level = _classify_with_rules(rules, {"task_type": "scheduled", "event_type": "task_failed"})
        assert level == 2

    def test_first_match_wins(self):
        """When multiple rules match, only the first is applied."""
        rules = [
            {"match": {"task_type": "dreaming"}, "set_level": 0},
            {"match": {"task_type": "dreaming"}, "set_level": 5},  # never reached
        ]
        level = _classify_with_rules(rules, {"task_type": "dreaming", "event_type": "task_failed"})
        assert level == 0

    def test_no_match_falls_back_to_source_rules(self):
        """When no event rule matches, source_rules min/max apply."""
        # No event rules — agent task_completed with notify_user=False → base 0
        # source_rules["agent"]["min_level"] = 2
        rules = []
        level = _classify_with_rules(rules, {"task_type": "agent", "event_type": "task_completed"})
        assert level == 2  # source_rules min_level kicks in

    def test_set_level_blocks_source_rules(self):
        """A matching event rule blocks source_rules from being applied."""
        # dreaming source_rules say max_level=1; but event rule overrides with set_level=3
        rules = [{"match": {"task_type": "dreaming"}, "set_level": 3}]
        level = _classify_with_rules(rules, {"task_type": "dreaming", "event_type": "task_completed"})
        assert level == 3  # not capped by source_rules max_level=1

    def test_critical_severity_not_overridden_by_max_level_rule(self):
        """A set_level rule on a different event_type doesn't affect unmatched events."""
        rules = [{"match": {"task_type": "dreaming", "event_type": "task_failed"}, "set_level": 1}]
        # critical severity — different event, no rule matches
        level = _classify_with_rules(rules, {"task_type": "dreaming", "severity": "critical"})
        # base = 5 (critical severity), dreaming max_level=1 applies via source_rules
        assert level == 1  # source_rules cap (no matching event rule)


# ---------------------------------------------------------------------------
# Config file event_rules sanity check
# ---------------------------------------------------------------------------

class TestConfigEventRules:

    def test_config_event_rules_load(self):
        """attention_routing.json event_rules must be a non-empty list."""
        rules = _load_event_rules()
        assert isinstance(rules, list)
        assert len(rules) > 0

    def test_each_rule_has_match_and_action(self):
        """Every event rule must have a 'match' dict and at least one action key."""
        action_keys = {"set_level", "min_level", "max_level"}
        for rule in _load_event_rules():
            if rule.get("_comment"):
                pass  # comment-only rules are skipped by _rule_matches
            assert "match" in rule, f"Rule missing 'match': {rule}"
            assert action_keys & set(rule.keys()), f"Rule has no action key: {rule}"

    def test_dreaming_failure_set_to_1(self):
        """The config rule caps dreaming failures at level 1."""
        from app.mcp.adapters import attention_classifier as ac
        ac._SOURCE_RULES = None
        ac._EVENT_RULES = None  # force reload from file
        AttentionClassifier.reload_rules()
        level = AttentionClassifier.classify({"task_type": "dreaming", "event_type": "task_failed"})
        ac._SOURCE_RULES = None
        ac._EVENT_RULES = None
        assert level == 1

    def test_security_sentinel_failure_set_to_5(self):
        """The config rule escalates security_sentinel failures to level 5."""
        from app.mcp.adapters import attention_classifier as ac
        ac._SOURCE_RULES = None
        ac._EVENT_RULES = None
        AttentionClassifier.reload_rules()
        level = AttentionClassifier.classify({
            "task_type": "assistant",
            "role_id": "security_sentinel",
            "event_type": "task_failed",
        })
        ac._SOURCE_RULES = None
        ac._EVENT_RULES = None
        assert level == 5
