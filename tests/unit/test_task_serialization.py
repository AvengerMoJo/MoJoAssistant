"""Unit tests for Task.to_dict()/from_dict() config-key durability.

Underscore-prefixed task.config keys are stripped on serialization by
default (most are runtime-only: backends, HTTP clients). A durable-prefix
allowlist (_DURABLE_CONFIG_KEY_PREFIXES) keeps specific subsystems' stamps
alive across saves. Found live 2026-09-23: DiscordHITLAdapter's
_hitl_posted_at dedup stamp (app/mcp/adapters/hitl/discord.py) was written
correctly but silently dropped on every disk save because only "_qm_" was
allowlisted -- the stamp never survived even a single save, so every
restart's catch-up re-posted every still-open HITL question as a fresh
duplicate in Discord.
"""

from __future__ import annotations

import unittest

from app.scheduler.models import Task, TaskPriority, TaskType


def _make_task(config):
    return Task(
        id="t1",
        type=TaskType.CUSTOM,
        priority=TaskPriority.MEDIUM,
        config=config,
        created_by="test",
    )


class TestDurableConfigKeys(unittest.TestCase):
    def test_hitl_posted_at_survives_round_trip(self):
        task = _make_task({"_hitl_posted_at": "2026-09-23T20:15:00"})
        restored = Task.from_dict(task.to_dict())
        self.assertEqual(
            restored.config.get("_hitl_posted_at"), "2026-09-23T20:15:00"
        )

    def test_qm_prefixed_keys_still_survive_round_trip(self):
        task = _make_task({"_qm_restart_count": 2, "_qm_escalated_at:foo": "x"})
        restored = Task.from_dict(task.to_dict())
        self.assertEqual(restored.config.get("_qm_restart_count"), 2)
        self.assertEqual(restored.config.get("_qm_escalated_at:foo"), "x")

    def test_unrecognized_underscore_keys_are_stripped(self):
        """Runtime-only objects (e.g. _opencode_client, _sandbox_handle) must
        NOT survive serialization -- they hold process references that don't
        survive JSON encoding."""
        task = _make_task({"_opencode_client": object(), "_sandbox_handle": object()})
        data = task.to_dict()
        self.assertNotIn("_opencode_client", data["config"])
        self.assertNotIn("_sandbox_handle", data["config"])

    def test_non_underscore_keys_always_survive(self):
        task = _make_task({"prompt": "do the thing", "session_id": "sess_1"})
        restored = Task.from_dict(task.to_dict())
        self.assertEqual(restored.config.get("prompt"), "do the thing")
        self.assertEqual(restored.config.get("session_id"), "sess_1")

    def test_callables_are_never_serialized_even_with_durable_prefix(self):
        task = _make_task({"_hitl_callback": lambda: None})
        data = task.to_dict()
        self.assertNotIn("_hitl_callback", data["config"])


if __name__ == "__main__":
    unittest.main()
