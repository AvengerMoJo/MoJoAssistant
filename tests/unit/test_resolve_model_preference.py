"""Tests for AgenticExecutor._resolve_model_preference.

Incident 2026-07-22: community_host's role config had model_preference="local"
(a generic tier hint, redundant with local_only=true), not a resource ID or a
real model name. It wasn't caught by the resource-ID compatibility check, so
it fell through and was used as a literal model_override -- every request
sent {"model": "local"} to LMStudio, which isn't a real model, and every
single local backend 400'd. See
~/.memory/research/community_host_tier_boundary_fix_2607.md.
"""
import unittest
from unittest.mock import MagicMock

from app.scheduler.agentic_executor import AgenticExecutor


def _resource(model: str):
    r = MagicMock()
    r.model = model
    return r


class TestResolveModelPreference(unittest.TestCase):
    def setUp(self):
        self.resources = {
            "lmstudio_qwen36_27b_mtp": _resource("qwen3.6-27b-mtp"),
            "lmstudio_qwen35b": _resource("qwen/qwen3.5-35b-a3b"),
        }

    def test_none_input_returns_all_none(self):
        result = AgenticExecutor._resolve_model_preference(None, self.resources)
        self.assertEqual(result, (None, None, None))

    def test_empty_string_returns_all_none(self):
        result = AgenticExecutor._resolve_model_preference("", self.resources)
        self.assertEqual(result, (None, None, None))

    def test_matching_resource_id_resolves_as_pin(self):
        result = AgenticExecutor._resolve_model_preference("lmstudio_qwen35b", self.resources)
        self.assertEqual(result, ("lmstudio_qwen35b", None, None))

    def test_matching_model_field_resolves_as_literal_override(self):
        # rebecca's documented use case
        result = AgenticExecutor._resolve_model_preference("qwen3.6-27b-mtp", self.resources)
        self.assertEqual(result, (None, "qwen3.6-27b-mtp", None))

    def test_generic_tier_hint_is_rejected_with_warning(self):
        # the exact community_host incident: "local" is neither a resource
        # ID nor any resource's model field
        resource_id, model_override, warning = AgenticExecutor._resolve_model_preference(
            "local", self.resources
        )
        self.assertIsNone(resource_id)
        self.assertIsNone(model_override)
        self.assertIsNotNone(warning)
        self.assertIn("local", warning)

    def test_unrecognized_value_never_becomes_a_literal_override(self):
        # Defense-in-depth: whatever garbage is passed, it must never come
        # back as model_override unless it's a real resource's model field.
        for garbage in ["cloud", "auto", "gpt-4-ish", ""]:
            _, model_override, _ = AgenticExecutor._resolve_model_preference(
                garbage, self.resources
            )
            self.assertIsNone(model_override, f"{garbage!r} should never resolve as a literal override")


if __name__ == "__main__":
    unittest.main()
