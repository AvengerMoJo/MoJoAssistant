"""Tests for self-tunable role parameters."""

import pytest
from app.memory.self_tunable import (
    TunableParams,
    validate_update,
    apply_tunable_update,
    DEFAULT_TUNABLE,
    IMMUTABLE,
)


class TestTunableParams:
    def test_from_role_default(self):
        role = {"id": "test", "name": "Test"}
        params = TunableParams.from_role(role)
        assert "temperature" in params.tunable
        assert "id" in params.immutable

    def test_from_role_custom_tunable(self):
        role = {
            "id": "test",
            "self_tunable_params": {
                "fields": ["custom_field"],
                "overrides": [],
            },
        }
        params = TunableParams.from_role(role)
        assert "custom_field" in params.tunable
        assert "temperature" in params.tunable  # default still included

    def test_from_role_list_format(self):
        role = {
            "id": "test",
            "self_tunable_params": ["custom_field"],
        }
        params = TunableParams.from_role(role)
        assert "custom_field" in params.tunable

    def test_is_tunable_default(self):
        params = TunableParams()
        assert params.is_tunable("temperature") is True
        assert params.is_tunable("max_iterations") is True

    def test_is_immutable_default(self):
        params = TunableParams()
        assert params.is_immutable("id") is True
        assert params.is_immutable("name") is True
        assert params.is_immutable("capabilities") is True

    def test_validate_update_accepts_tunable(self):
        params = TunableParams()
        updates = {"temperature": 0.8, "max_iterations": 20}
        validated = params.validate_update(updates)
        assert validated == {"temperature": 0.8, "max_iterations": 20}

    def test_validate_update_rejects_immutable(self):
        params = TunableParams()
        updates = {"temperature": 0.8, "id": "new_id", "name": "new_name"}
        validated = params.validate_update(updates)
        assert "temperature" in validated
        assert "id" not in validated
        assert "name" not in validated

    def test_get_tunable_list(self):
        params = TunableParams()
        tunable = params.get_tunable_list()
        assert "temperature" in tunable
        assert "id" not in tunable
        # Should be sorted
        assert tunable == sorted(tunable)

    def test_override_immutable(self):
        role = {
            "id": "test",
            "self_tunable_params": {
                "fields": [],
                "overrides": ["id"],  # Make id tunable
            },
        }
        params = TunableParams.from_role(role)
        assert params.is_tunable("id") is True


class TestValidateUpdate:
    def test_function(self):
        params = TunableParams()
        result = validate_update(params, {"temperature": 0.5})
        assert result == {"temperature": 0.5}


class TestApplyTunableUpdate:
    def test_applies_tunable(self):
        role = {
            "id": "test",
            "temperature": 0.7,
            "max_iterations": 10,
        }
        updated = apply_tunable_update(role, {"temperature": 0.9})
        assert updated["temperature"] == 0.9
        assert updated["max_iterations"] == 10

    def test_rejects_immutable(self):
        role = {
            "id": "test",
            "name": "Test",
            "temperature": 0.7,
        }
        updated = apply_tunable_update(role, {"name": "New Name"})
        assert updated["name"] == "Test"  # unchanged

    def test_updates_timestamp(self):
        role = {"id": "test", "temperature": 0.7}
        updated = apply_tunable_update(role, {"temperature": 0.9})
        assert "updated_at" in updated

    def test_no_changes_returns_same_dict(self):
        role = {"id": "test", "temperature": 0.7}
        updated = apply_tunable_update(role, {"id": "new"})
        assert updated is role  # same object
