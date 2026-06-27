"""Tests for eval_consolidation module."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.memory.eval_consolidation import (
    ConsolidationEvaluator,
    ConsolidationOutcome,
    EvalResult,
)


@pytest.fixture
def mock_memory_service():
    """Mock memory service that returns configurable relevance scores."""
    service = MagicMock()
    # Default: return 3 results with relevance scores
    service.get_context_for_query.return_value = [
        {"relevance_score": 0.8},
        {"relevance_score": 0.6},
        {"relevance_score": 0.4},
    ]
    return service


@pytest.fixture
def mock_storage(tmp_path):
    """Mock storage with base_path."""
    storage = MagicMock()
    storage.base_path = tmp_path / "storage"
    storage.base_path.mkdir(parents=True, exist_ok=True)
    # Create some test data
    (storage.base_path / "test.json").write_text('{"test": true}')
    return storage


class TestEvalResult:
    def test_mean_score(self):
        result = EvalResult(mean_score=0.5, query_count=3, scores={"q1": 0.6, "q2": 0.4, "q3": 0.5})
        assert result.mean_score == 0.5
        assert result.query_count == 3

    def test_to_dict(self):
        result = EvalResult(mean_score=0.5, query_count=1, scores={"q1": 0.5})
        d = result.to_dict()
        assert d["mean_score"] == 0.5
        assert d["query_count"] == 1


class TestConsolidationOutcome:
    def test_delta_with_both_results(self):
        pre = EvalResult(mean_score=0.5, query_count=1, scores={})
        post = EvalResult(mean_score=0.6, query_count=1, scores={})
        outcome = ConsolidationOutcome(pre=pre, post=post, committed=True)
        assert outcome.delta == pytest.approx(0.1)

    def test_delta_without_post(self):
        pre = EvalResult(mean_score=0.5, query_count=1, scores={})
        outcome = ConsolidationOutcome(pre=pre, post=None, committed=True)
        assert outcome.delta is None

    def test_to_dict(self):
        outcome = ConsolidationOutcome(pre=None, post=None, committed=False, rollback_reason="test")
        d = outcome.to_dict()
        assert d["committed"] is False
        assert d["rollback_reason"] == "test"


class TestConsolidationEvaluator:
    def test_evaluate_returns_scores(self, mock_memory_service):
        evaluator = ConsolidationEvaluator(
            memory_service=mock_memory_service,
            role_id="test",
        )
        result = evaluator.evaluate()
        assert result.mean_score > 0
        assert result.query_count == 5  # default queries

    def test_evaluate_with_no_memory_service(self):
        evaluator = ConsolidationEvaluator(memory_service=None)
        result = evaluator.evaluate()
        assert result.mean_score == 0.0
        assert result.query_count == 0

    def test_guarded_consolidation_commits_on_improvement(self, mock_memory_service):
        # First call: lower scores, second call: higher scores
        mock_memory_service.get_context_for_query.side_effect = [
            [{"relevance_score": 0.5}],  # pre q1
            [{"relevance_score": 0.5}],  # pre q2
            [{"relevance_score": 0.5}],  # pre q3
            [{"relevance_score": 0.5}],  # pre q4
            [{"relevance_score": 0.5}],  # pre q5
            [{"relevance_score": 0.8}],  # post q1
            [{"relevance_score": 0.8}],  # post q2
            [{"relevance_score": 0.8}],  # post q3
            [{"relevance_score": 0.8}],  # post q4
            [{"relevance_score": 0.8}],  # post q5
        ]

        evaluator = ConsolidationEvaluator(
            memory_service=mock_memory_service,
            role_id="test",
        )

        with evaluator.guarded_consolidation() as outcome:
            # Simulate dreaming work
            pass

        assert outcome.committed is True
        assert outcome.delta > 0

    def test_guarded_consolidation_rollback_on_degradation(self, mock_memory_service, mock_storage):
        # First call: higher scores, second call: lower scores
        mock_memory_service.get_context_for_query.side_effect = [
            [{"relevance_score": 0.8}],  # pre q1
            [{"relevance_score": 0.8}],  # pre q2
            [{"relevance_score": 0.8}],  # pre q3
            [{"relevance_score": 0.8}],  # pre q4
            [{"relevance_score": 0.8}],  # pre q5
            [{"relevance_score": 0.3}],  # post q1
            [{"relevance_score": 0.3}],  # post q2
            [{"relevance_score": 0.3}],  # post q3
            [{"relevance_score": 0.3}],  # post q4
            [{"relevance_score": 0.3}],  # post q5
        ]

        evaluator = ConsolidationEvaluator(
            memory_service=mock_memory_service,
            storage=mock_storage,
            role_id="test",
            degradation_threshold=0.03,
        )

        with evaluator.guarded_consolidation() as outcome:
            # Simulate dreaming work that degrades quality
            pass

        assert outcome.committed is False
        assert "degraded" in outcome.rollback_reason.lower()

    def test_guarded_consolidation_empty_kb_always_commits(self, mock_memory_service):
        # First call: no results (empty KB), second call: some results
        mock_memory_service.get_context_for_query.side_effect = [
            [],  # pre q1
            [],  # pre q2
            [],  # pre q3
            [],  # pre q4
            [],  # pre q5
            [{"relevance_score": 0.5}],  # post q1
            [{"relevance_score": 0.5}],  # post q2
            [{"relevance_score": 0.5}],  # post q3
            [{"relevance_score": 0.5}],  # post q4
            [{"relevance_score": 0.5}],  # post q5
        ]

        evaluator = ConsolidationEvaluator(
            memory_service=mock_memory_service,
            role_id="test",
        )

        with evaluator.guarded_consolidation() as outcome:
            pass

        assert outcome.committed is True

    def test_custom_query_set(self, mock_memory_service, tmp_path):
        query_file = tmp_path / "queries.json"
        query_file.write_text(json.dumps(["custom query 1", "custom query 2"]))

        evaluator = ConsolidationEvaluator(
            memory_service=mock_memory_service,
            query_set_path=str(query_file),
            role_id="test",
        )

        result = evaluator.evaluate()
        assert result.query_count == 2

    def test_load_queries_from_config(self, mock_memory_service, tmp_path, monkeypatch):
        config_dir = tmp_path / ".memory" / "config"
        config_dir.mkdir(parents=True)
        query_file = config_dir / "eval_query_set.json"
        query_file.write_text(json.dumps(["config query"]))

        # Patch the config path in the module
        import app.memory.eval_consolidation as mod
        original_load = mod.ConsolidationEvaluator._load_queries

        def patched_load(self, path):
            # Try explicit path first
            if path:
                try:
                    return json.loads(Path(path).read_text())
                except Exception:
                    pass
            # Try patched config path
            config_path = tmp_path / ".memory" / "config" / "eval_query_set.json"
            if config_path.exists():
                try:
                    return json.loads(config_path.read_text())
                except Exception:
                    pass
            return list(mod._DEFAULT_QUERIES)

        monkeypatch.setattr(mod.ConsolidationEvaluator, "_load_queries", patched_load)

        evaluator = ConsolidationEvaluator(
            memory_service=mock_memory_service,
            role_id="test",
        )

        assert evaluator._query_set == ["config query"]
