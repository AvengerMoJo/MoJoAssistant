"""Tests for conflict diagnosis module."""

import pytest
from unittest.mock import MagicMock

from app.memory.conflict_diagnosis import (
    ConflictDiagnoser,
    ConflictReport,
    DiagnosisSummary,
)


@pytest.fixture
def mock_memory_service():
    """Mock memory service with configurable results."""
    service = MagicMock()
    return service


class TestConflictReport:
    def test_to_dict(self):
        report = ConflictReport(
            unit_a_id="a1",
            unit_b_id="b1",
            unit_a_text="text a",
            unit_b_text="text b",
            query="test",
            score_a=0.8,
            score_b=0.7,
            distance=0.5,
            conflict_type="contradiction",
            reason="conflicting facts",
            severity="high",
        )
        d = report.to_dict()
        assert d["unit_a_id"] == "a1"
        assert d["conflict_type"] == "contradiction"
        assert d["severity"] == "high"


class TestDiagnosisSummary:
    def test_to_dict(self):
        summary = DiagnosisSummary(
            total_queries=5,
            total_conflicts=2,
            contradictions=1,
            staleness=0,
            redundancy=1,
        )
        d = summary.to_dict()
        assert d["total_queries"] == 5
        assert d["total_conflicts"] == 2
        assert d["contradictions"] == 1


class TestConflictDiagnoser:
    def test_no_memory_service(self):
        diagnoser = ConflictDiagnoser(memory_service=None)
        result = diagnoser.diagnose()
        assert result.total_conflicts == 0

    def test_no_results(self, mock_memory_service):
        mock_memory_service.get_context_for_query.return_value = []
        diagnoser = ConflictDiagnoser(memory_service=mock_memory_service)
        result = diagnoser.diagnose(query_set=["test"])
        assert result.total_conflicts == 0

    def test_single_result_no_conflict(self, mock_memory_service):
        mock_memory_service.get_context_for_query.return_value = [
            {"content": "fact", "relevance_score": 0.8}
        ]
        diagnoser = ConflictDiagnoser(memory_service=mock_memory_service)
        result = diagnoser.diagnose(query_set=["test"])
        assert result.total_conflicts == 0

    def test_contradiction_detected(self, mock_memory_service):
        # Two high-relevance results with very different content
        mock_memory_service.get_context_for_query.return_value = [
            {
                "id": "unit1",
                "content": "The user prefers dark mode and uses vim",
                "relevance_score": 0.9,
                "created_at": "2026-06-20T00:00:00Z",
            },
            {
                "id": "unit2",
                "content": "The user prefers light mode and uses emacs",
                "relevance_score": 0.85,
                "created_at": "2026-06-21T00:00:00Z",
            },
        ]
        diagnoser = ConflictDiagnoser(
            memory_service=mock_memory_service,
            contradiction_threshold=0.3,
        )
        result = diagnoser.diagnose(query_set=["user preferences"])
        assert result.contradictions >= 1

    def test_redundancy_detected(self, mock_memory_service):
        # Two nearly identical results
        mock_memory_service.get_context_for_query.return_value = [
            {
                "id": "unit1",
                "content": "The project uses FastAPI for the web server",
                "relevance_score": 0.9,
                "created_at": "2026-06-20T00:00:00Z",
            },
            {
                "id": "unit2",
                "content": "The project uses FastAPI for the web server",
                "relevance_score": 0.85,
                "created_at": "2026-06-20T00:00:00Z",
            },
        ]
        diagnoser = ConflictDiagnoser(
            memory_service=mock_memory_service,
            redundancy_threshold=0.95,
        )
        result = diagnoser.diagnose(query_set=["project architecture"])
        assert result.redundancy >= 1

    def test_staleness_detected(self, mock_memory_service):
        # Two similar results with very different timestamps
        mock_memory_service.get_context_for_query.return_value = [
            {
                "id": "unit1",
                "content": "The user prefers the old authentication system with JWT tokens",
                "relevance_score": 0.9,
                "created_at": "2025-01-01T00:00:00Z",
            },
            {
                "id": "unit2",
                "content": "The user prefers the new authentication system with OAuth tokens",
                "relevance_score": 0.85,
                "created_at": "2026-06-20T00:00:00Z",
            },
        ]
        diagnoser = ConflictDiagnoser(memory_service=mock_memory_service)
        result = diagnoser.diagnose(query_set=["user preferences"])
        # Should detect either staleness or contradiction
        assert result.total_conflicts >= 1

    def test_custom_query_set(self, mock_memory_service):
        mock_memory_service.get_context_for_query.return_value = []
        diagnoser = ConflictDiagnoser(memory_service=mock_memory_service)
        result = diagnoser.diagnose(query_set=["q1", "q2", "q3"])
        assert result.total_queries == 3

    def test_default_query_set(self, mock_memory_service):
        mock_memory_service.get_context_for_query.return_value = []
        diagnoser = ConflictDiagnoser(memory_service=mock_memory_service)
        result = diagnoser.diagnose()
        assert result.total_queries == 5  # default 5 queries
