"""Tests for dynamic_answers.py -- the fix for hardcoded benchmark answers
that go stale the moment live system state changes (resource_pool.json
growth, config/ file changes, role edits).

Root cause: check_answer() used to compare a model's response against a
frozen `correct_answer` string, snapshotted whenever the task was
authored. Any task about live state (resource counts, priorities, file
listings) drifted stale the next time that state changed -- failing even
a model that computed the true, current answer correctly. The fix:
`correct_answer_fn` on a task names a function here that computes the
expected answer fresh, every time, so the check stays correct regardless
of when the task runs.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "benchmarks"))

import dynamic_answers as da  # noqa: E402
from dynamic_answers import resolve_dynamic_answer, REGISTRY  # noqa: E402


class TestResolveDynamicAnswer(unittest.TestCase):
    def test_unknown_function_name_returns_none(self):
        self.assertIsNone(resolve_dynamic_answer("no_such_function"))

    def test_every_registered_function_is_callable_with_no_args(self):
        # Cheap sanity check that the registry itself isn't broken --
        # doesn't assert specific values (those depend on live system
        # state), just that every entry resolves without raising.
        for name in REGISTRY:
            result = resolve_dynamic_answer(name)
            self.assertIsInstance(result, str, f"{name} did not return a str")


class TestResourcePoolDerivedAnswers(unittest.TestCase):
    """Use a fake resource pool so these tests don't depend on the real
    live ~/.memory/config/resource_pool.json contents."""

    def setUp(self):
        self.fake_pool = {
            "a": {"enabled": True, "type": "local", "tier": "free", "priority": 4, "model": "model-a"},
            "b": {"enabled": True, "type": "local", "tier": "free", "priority": 2, "model": "model-b"},
            "c": {"enabled": False, "type": "local", "tier": "free", "priority": 1, "model": "model-c"},
            "d": {"enabled": True, "type": "api", "tier": "free_api", "priority": 90, "model": "model-d"},
        }
        patcher = patch.object(da, "_load_resource_pool", return_value=self.fake_pool)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_total_count(self):
        self.assertEqual(da.resource_pool_total_count(), "4")

    def test_enabled_count(self):
        self.assertEqual(da.resource_pool_enabled_count(), "3")  # c is disabled

    def test_lowest_priority_excludes_disabled(self):
        # c has priority 1 (lowest overall) but is disabled -> excluded.
        # b has priority 2, the lowest among enabled.
        self.assertEqual(da.resource_pool_lowest_priority_model_name(), "model-b")

    def test_enabled_free_tier_names(self):
        self.assertEqual(da.resource_pool_enabled_free_tier_names(), "a,b")

    def test_api_tier_count_and_models(self):
        self.assertEqual(da.resource_pool_api_tier_count_and_models(), "count=1;models=model-d")

    def test_reflects_state_change_immediately(self):
        # The whole point: add a resource, the answer changes on the next
        # call with no code change and no manual JSON regeneration.
        self.assertEqual(da.resource_pool_total_count(), "4")
        self.fake_pool["e"] = {"enabled": True, "type": "local", "tier": "free", "priority": 5, "model": "model-e"}
        self.assertEqual(da.resource_pool_total_count(), "5")


class TestConfigDirDerivedAnswers(unittest.TestCase):
    def test_excludes_non_config_log_file(self):
        # tool_operation_logs.json is a multi-MB runtime log, not config --
        # it must never be counted, or the answer is unstable by the minute.
        with tempfile.TemporaryDirectory() as td:
            config_dir = Path(td) / "config"
            config_dir.mkdir()
            (config_dir / "real_config.json").write_text('{"a": 1}\n{"b": 2}\n')
            (config_dir / "tool_operation_logs.json").write_text("\n".join(["x"] * 100000))

            with patch.object(da, "PROJECT_ROOT", Path(td)):
                names = da.config_json_file_names()
                total_lines = da.config_total_line_count()

            self.assertIn("real_config.json", names)
            self.assertNotIn("tool_operation_logs.json", names)
            self.assertEqual(total_lines, "2")  # only real_config.json's 2 lines

    def test_line_count_stable_across_log_growth(self):
        # The direct proof this fix targets: the log file growing must not
        # change the answer at all.
        with tempfile.TemporaryDirectory() as td:
            config_dir = Path(td) / "config"
            config_dir.mkdir()
            (config_dir / "real_config.json").write_text("line1\nline2\nline3\n")
            log = config_dir / "tool_operation_logs.json"
            log.write_text("x\n" * 10)

            with patch.object(da, "PROJECT_ROOT", Path(td)):
                before = da.config_total_line_count()
                log.write_text("x\n" * 3_000_000)  # simulate massive log growth
                after = da.config_total_line_count()

            self.assertEqual(before, after)
            self.assertEqual(before, "3")


class TestRoleDerivedAnswers(unittest.TestCase):
    def test_avg_max_iterations_for_coding_agent_roles_only(self):
        fake_roles = {
            "popo": {"executor": "coding_agent", "max_iterations": 20},
            "carl": {"executor": "coding_agent", "max_iterations": 30},
            "anna": {"executor": "agentic", "max_iterations": 999},  # excluded
        }
        with patch.object(da, "_load_roles", return_value=fake_roles):
            self.assertEqual(da.coding_agent_roles_avg_max_iterations(), "25.00")

    def test_word_count_reflects_live_prompt(self):
        with patch.object(da, "_load_roles", return_value={"popo": {"system_prompt": "one two three four"}}):
            self.assertEqual(da.popo_system_prompt_word_count(), "4")


class TestRolesCountDefaultPortEmbeddingModel(unittest.TestCase):
    """cellC_001's 3-fact composite answer -- role count was previously
    hardcoded "16" and went stale (live is 17). All three facts are now
    computed fresh."""

    def test_combines_role_count_port_and_embedding_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".env.example").write_text("SOME_VAR=1\nSERVER_PORT=9000\nOTHER=2\n")
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "embedding_config.json").write_text(json.dumps({
                "embedding_models": {"default": {"model_name": "test/embed-model"}}
            }))
            fake_roles = {"a": {}, "b": {}, "c": {}}
            with patch.object(da, "PROJECT_ROOT", root), \
                 patch.object(da, "_load_roles", return_value=fake_roles):
                result = da.roles_count_default_port_embedding_model()
            self.assertEqual(result, "3;9000;test/embed-model")

    def test_reflects_role_count_growth(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".env.example").write_text("SERVER_PORT=8000\n")
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "embedding_config.json").write_text(json.dumps({
                "embedding_models": {"default": {"model_name": "m"}}
            }))
            with patch.object(da, "PROJECT_ROOT", root):
                with patch.object(da, "_load_roles", return_value={"a": {}}):
                    before = da.roles_count_default_port_embedding_model()
                with patch.object(da, "_load_roles", return_value={"a": {}, "b": {}}):
                    after = da.roles_count_default_port_embedding_model()
            self.assertEqual(before.split(";")[0], "1")
            self.assertEqual(after.split(";")[0], "2")


if __name__ == "__main__":
    unittest.main()
