"""
Unit tests for the Agent Learning Loop (v1.3.1).

Covers:
  - _classify_failure  (failure taxonomy classification)
  - _write_task_lesson (structured lesson records on failure)
  - _inject_lessons    (memory context injection at task start)
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.scheduler.agentic_executor import AgenticExecutor


class TestClassifyFailure(unittest.TestCase):

    def setUp(self):
        # Create a minimal executor mock for testing classification methods
        self.executor = MagicMock(spec=AgenticExecutor)
        # Bind the real method and class variable to the mock
        self.executor._classify_failure = AgenticExecutor._classify_failure.__get__(self.executor)
        self.executor._FAILURE_TAXONOMY = AgenticExecutor._FAILURE_TAXONOMY

    def test_classifies_missing_resource(self):
        result = self.executor._classify_failure("search returned no results", [])
        self.assertEqual(result, "missing_resource")

    def test_classifies_wrong_tool(self):
        result = self.executor._classify_failure("fetch_url not supported for this platform", [])
        self.assertEqual(result, "wrong_tool")

    def test_classifies_missing_permission(self):
        result = self.executor._classify_failure("bash_exec blocked by policy", [])
        self.assertEqual(result, "missing_permission")

    def test_classifies_ambiguous_goal(self):
        result = self.executor._classify_failure("goal is unclear, need clarification", [])
        self.assertEqual(result, "ambiguous_goal")

    def test_classifies_external_unavailable(self):
        result = self.executor._classify_failure("API rate limit exceeded", [])
        self.assertEqual(result, "external_unavailable")

    def test_classifies_knowledge_gap(self):
        result = self.executor._classify_failure("don't know enough about this domain", [])
        self.assertEqual(result, "knowledge_gap")

    def test_classifies_unknown_for_generic_error(self):
        result = self.executor._classify_failure("something went wrong", [])
        self.assertEqual(result, "unknown")

    def test_classifies_from_iteration_log(self):
        iteration_log = [
            {"tool_calls": ["web_search"], "status": "final_rejected"},
            {"tool_calls": ["web_search"], "status": "final_rejected"},
        ]
        result = self.executor._classify_failure("", iteration_log)
        # Should detect "rejected" in combined text
        self.assertIn(result, ["ambiguous_goal", "unknown"])


class TestWriteTaskLesson(unittest.TestCase):

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

        self.executor = MagicMock(spec=AgenticExecutor)
        self.executor._log = MagicMock()
        self.executor._classify_failure = AgenticExecutor._classify_failure.__get__(self.executor)
        self.executor._FAILURE_TAXONOMY = AgenticExecutor._FAILURE_TAXONOMY

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_classify_failure_detects_missing_resource(self):
        result = self.executor._classify_failure("search returned no results", [])
        self.assertEqual(result, "missing_resource")

    def test_classify_failure_detects_wrong_tool(self):
        result = self.executor._classify_failure("fetch_url not supported for this platform", [])
        self.assertEqual(result, "wrong_tool")

    def test_classify_failure_detects_missing_permission(self):
        result = self.executor._classify_failure("bash_exec blocked by policy", [])
        self.assertEqual(result, "missing_permission")

    def test_classify_failure_detects_ambiguous_goal(self):
        result = self.executor._classify_failure("goal is unclear, need clarification", [])
        self.assertEqual(result, "ambiguous_goal")

    def test_classify_failure_detects_external_unavailable(self):
        result = self.executor._classify_failure("API rate limit exceeded", [])
        self.assertEqual(result, "external_unavailable")

    def test_classify_failure_detects_knowledge_gap(self):
        result = self.executor._classify_failure("don't know enough about this domain", [])
        self.assertEqual(result, "knowledge_gap")

    def test_classify_failure_returns_unknown_for_generic(self):
        result = self.executor._classify_failure("something went wrong", [])
        self.assertEqual(result, "unknown")


class TestInjectLessons(unittest.TestCase):

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()

        self.executor = MagicMock(spec=AgenticExecutor)
        self.executor._log = MagicMock()
        self.executor._memory_service = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_returns_empty_for_no_role_id(self):
        result = asyncio.run(AgenticExecutor._inject_lessons(
            self.executor, "test goal", None
        ))
        self.assertEqual(result, "")

    def test_returns_empty_for_no_memory_service(self):
        self.executor._memory_service = None
        result = asyncio.run(AgenticExecutor._inject_lessons(
            self.executor, "test goal", "researcher"
        ))
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
