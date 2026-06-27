"""Tests for MemoryAction module."""

import pytest
from app.memory.memory_action import MemoryAction, MemoryActionType


class TestMemoryActionType:
    def test_values(self):
        assert MemoryActionType.INSERT_UNIT.value == "insert_unit"
        assert MemoryActionType.UPDATE_FACTS.value == "update_facts"
        assert MemoryActionType.MERGE_UNITS.value == "merge_units"
        assert MemoryActionType.RETIRE_STALE.value == "retire_stale"

    def test_from_string(self):
        assert MemoryActionType("insert_unit") == MemoryActionType.INSERT_UNIT


class TestMemoryAction:
    def test_insert_validation(self):
        action = MemoryAction(action_type=MemoryActionType.INSERT_UNIT, content="fact")
        action.validate()  # should not raise

    def test_insert_requires_content(self):
        action = MemoryAction(action_type=MemoryActionType.INSERT_UNIT)
        with pytest.raises(ValueError, match="INSERT_UNIT requires content"):
            action.validate()

    def test_update_validation(self):
        action = MemoryAction(
            action_type=MemoryActionType.UPDATE_FACTS,
            target_ids=["id1"],
            content="revised",
        )
        action.validate()

    def test_update_requires_one_target(self):
        action = MemoryAction(
            action_type=MemoryActionType.UPDATE_FACTS,
            target_ids=["id1", "id2"],
            content="revised",
        )
        with pytest.raises(ValueError, match="exactly 1"):
            action.validate()

    def test_update_requires_content(self):
        action = MemoryAction(
            action_type=MemoryActionType.UPDATE_FACTS,
            target_ids=["id1"],
        )
        with pytest.raises(ValueError, match="UPDATE_FACTS requires content"):
            action.validate()

    def test_merge_validation(self):
        action = MemoryAction(
            action_type=MemoryActionType.MERGE_UNITS,
            target_ids=["id1", "id2"],
        )
        action.validate()

    def test_merge_requires_two_targets(self):
        action = MemoryAction(
            action_type=MemoryActionType.MERGE_UNITS,
            target_ids=["id1"],
        )
        with pytest.raises(ValueError, match="exactly 2"):
            action.validate()

    def test_retire_validation(self):
        action = MemoryAction(
            action_type=MemoryActionType.RETIRE_STALE,
            target_ids=["id1", "id2"],
        )
        action.validate()

    def test_retire_requires_targets(self):
        action = MemoryAction(action_type=MemoryActionType.RETIRE_STALE)
        with pytest.raises(ValueError, match="at least 1"):
            action.validate()

    def test_timestamp_auto_set(self):
        action = MemoryAction(action_type=MemoryActionType.INSERT_UNIT, content="test")
        assert action.timestamp != ""
        assert "T" in action.timestamp

    def test_to_dict(self):
        action = MemoryAction(
            action_type=MemoryActionType.INSERT_UNIT,
            content="test",
            reason="test reason",
            proposed_by="rebecca",
        )
        d = action.to_dict()
        assert d["action_type"] == "insert_unit"
        assert d["content"] == "test"
        assert d["reason"] == "test reason"
        assert d["proposed_by"] == "rebecca"

    def test_from_dict(self):
        d = {
            "action_type": "merge_units",
            "target_ids": ["id1", "id2"],
            "content": "merged",
            "metadata": {"key": "val"},
            "reason": "redundant",
            "proposed_by": "popo",
            "timestamp": "2026-06-27T00:00:00Z",
        }
        action = MemoryAction.from_dict(d)
        assert action.action_type == MemoryActionType.MERGE_UNITS
        assert action.target_ids == ["id1", "id2"]
        assert action.content == "merged"
        assert action.proposed_by == "popo"

    def test_from_dict_string_action_type(self):
        d = {"action_type": "insert_unit", "content": "test"}
        action = MemoryAction.from_dict(d)
        assert action.action_type == MemoryActionType.INSERT_UNIT
