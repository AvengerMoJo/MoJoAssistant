"""
v1.2.15 Unit Tests — task_report_v2 writer and FINAL_ANSWER section parser

Tests:
  - _parse_final_answer_sections: bullet-style structured answer
  - _parse_final_answer_sections: paragraph-style (no bullets) answer
  - _parse_final_answer_sections: plain answer with no sections
  - _parse_final_answer_sections: section boundary does not bleed into next header
  - _store_completion_artifact: writes correct v2 schema
  - _store_completion_artifact: status=completed when auto_extracted=False
  - _store_completion_artifact: status=completed_fallback when auto_extracted=True
  - _store_completion_artifact: review_status is always "pending_review"
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parents[2]))

from app.scheduler.agentic_executor import _parse_final_answer_sections


# ---------------------------------------------------------------------------
# _parse_final_answer_sections
# ---------------------------------------------------------------------------

class TestParseFinalAnswerSections(unittest.TestCase):

    BULLET_ANSWER = """\
**Completed:**
- Researched topic A
- Found 3 sources

**Findings:**
- Key finding one
- Key finding two

**Incomplete:**
- Still need to verify X

**Resume hint:**
- Continue from step 3
"""

    def test_bullet_completed_list(self):
        r = _parse_final_answer_sections(self.BULLET_ANSWER)
        self.assertEqual(r["completed"], ["Researched topic A", "Found 3 sources"])

    def test_bullet_findings_list(self):
        r = _parse_final_answer_sections(self.BULLET_ANSWER)
        self.assertEqual(r["findings"], ["Key finding one", "Key finding two"])

    def test_bullet_incomplete_list(self):
        r = _parse_final_answer_sections(self.BULLET_ANSWER)
        self.assertEqual(r["incomplete"], ["Still need to verify X"])

    def test_bullet_resume_hint(self):
        r = _parse_final_answer_sections(self.BULLET_ANSWER)
        self.assertEqual(r["resume_hint"], "Continue from step 3")

    def test_no_section_header_in_prior_list(self):
        """Boundary bug: **Findings:** header must NOT appear in completed list."""
        r = _parse_final_answer_sections(self.BULLET_ANSWER)
        for item in r["completed"]:
            self.assertNotIn("Findings", item,
                             f"Section header leaked into completed: {item!r}")
        for item in r["findings"]:
            self.assertNotIn("Incomplete", item,
                             f"Section header leaked into findings: {item!r}")

    def test_paragraph_style_sections(self):
        text = """\
**Completed:**
Researched three papers on context window allocation.
Summarized key strategies.

**Findings:**
Models perform best when context is split 60/40 between system and user.

**Incomplete:**
Did not test with streaming responses.

**Resume hint:**
Run streaming benchmark next.
"""
        r = _parse_final_answer_sections(text)
        self.assertIn("Researched three papers on context window allocation.", r["completed"])
        self.assertIn("Summarized key strategies.", r["completed"])
        self.assertIn("Models perform best when context is split 60/40 between system and user.", r["findings"])
        self.assertIn("Did not test with streaming responses.", r["incomplete"])
        self.assertEqual(r["resume_hint"], "Run streaming benchmark next.")

    def test_plain_answer_no_sections(self):
        text = "This is a plain FINAL_ANSWER with no structured sections."
        r = _parse_final_answer_sections(text)
        self.assertEqual(r["completed"], [])
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["incomplete"], [])
        self.assertEqual(r["resume_hint"], "")

    def test_empty_string(self):
        r = _parse_final_answer_sections("")
        self.assertEqual(r["completed"], [])
        self.assertEqual(r["resume_hint"], "")

    def test_missing_section_returns_empty(self):
        text = "**Completed:**\n- Done\n\n**Resume hint:**\nAll done."
        r = _parse_final_answer_sections(text)
        self.assertEqual(r["completed"], ["Done"])
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["incomplete"], [])
        self.assertEqual(r["resume_hint"], "All done.")


# ---------------------------------------------------------------------------
# _store_completion_artifact
# ---------------------------------------------------------------------------

class TestStoreCompletionArtifact(unittest.TestCase):

    def _make_executor(self, tmpdir: str):
        from app.scheduler.agentic_executor import AgenticExecutor
        from app.scheduler.capability_registry import CapabilityRegistry

        ex = AgenticExecutor.__new__(AgenticExecutor)
        ex._log = lambda msg, level="info": None
        ex._tool_registry = CapabilityRegistry()

        # Minimal session storage stub
        storage_stub = MagicMock()
        storage_stub._path.return_value = Path(tmpdir) / "session.json"
        ex._session_storage = storage_stub
        return ex

    def _make_task(self, task_id: str = "task-001"):
        from app.scheduler.models import Task, TaskStatus
        t = Task.__new__(Task)
        t.id = task_id
        t.status = TaskStatus.COMPLETED
        return t

    def _write_and_load(self, auto_extracted: bool) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            ex = self._make_executor(tmpdir)
            task = self._make_task()

            report_dir = Path(tmpdir) / "task_reports"
            report_dir.mkdir()

            with patch("app.config.paths.get_memory_subpath", return_value=str(report_dir)):
                ex._store_completion_artifact(
                    task=task,
                    role_id="rebecca",
                    goal="Research context strategies",
                    final_answer="**Completed:**\n- Done step 1\n\n**Findings:**\n- Finding A",
                    iteration_log=[{"status": "tool_use"}, {"status": "response"}],
                    duration_seconds=42.5,
                    auto_extracted=auto_extracted,
                    resource_id="lmstudio",
                    model="qwen3",
                )

            report_path = report_dir / "task-001.json"
            self.assertTrue(report_path.exists(), "report file was not written")
            with open(report_path) as f:
                return json.load(f)

    def test_schema_version(self):
        report = self._write_and_load(auto_extracted=False)
        self.assertEqual(report["schema_version"], "task_report_v2")

    def test_status_completed_when_not_auto_extracted(self):
        report = self._write_and_load(auto_extracted=False)
        self.assertEqual(report["status"], "completed")

    def test_status_completed_fallback_when_auto_extracted(self):
        report = self._write_and_load(auto_extracted=True)
        self.assertEqual(report["status"], "completed_fallback")

    def test_review_status_always_pending(self):
        for flag in (True, False):
            with self.subTest(auto_extracted=flag):
                report = self._write_and_load(auto_extracted=flag)
                self.assertEqual(report["review_status"], "pending_review")

    def test_structured_sections_written(self):
        report = self._write_and_load(auto_extracted=False)
        self.assertEqual(report["completed"], ["Done step 1"])
        self.assertEqual(report["findings"], ["Finding A"])

    def test_metrics_written(self):
        report = self._write_and_load(auto_extracted=False)
        self.assertEqual(report["metrics"]["tool_calls"], 1)
        self.assertAlmostEqual(report["metrics"]["duration_seconds"], 42.5)

    def test_provenance_written(self):
        report = self._write_and_load(auto_extracted=False)
        self.assertEqual(report["provenance"]["resource_id"], "lmstudio")
        self.assertEqual(report["provenance"]["model"], "qwen3")

    def test_role_id_written(self):
        report = self._write_and_load(auto_extracted=False)
        self.assertEqual(report["role_id"], "rebecca")


if __name__ == "__main__":
    unittest.main()
