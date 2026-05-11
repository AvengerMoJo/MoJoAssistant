"""Conformance tests for RetrievalStrategy implementations.

Any class claiming to be a RetrievalStrategy must pass all tests here.
"""

from __future__ import annotations

import math
import pytest
from typing import Any, Dict, List

from app.services.provider_contracts import RetrievalStrategy, ScoredResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidate(text: str, score_hint: float, source: str = "test") -> Dict[str, Any]:
    """Build a candidate dict with a synthetic embedding whose cosine sim with
    the unit query [1,0] equals score_hint."""
    perp = math.sqrt(max(0.0, 1.0 - score_hint ** 2))
    return {
        "text_content": text,
        "source": source,
        "embeddings": {
            "bge-m3:1024": [score_hint, perp],
        },
        "metadata": {"hint": score_hint},
    }


QUERY_EMBEDDING = [1.0, 0.0]  # unit vector along first axis

CANDIDATES = [
    _make_candidate("high relevance", 0.95),
    _make_candidate("medium relevance", 0.60),
    _make_candidate("low relevance", 0.25),  # below default threshold
    _make_candidate("knowledge item", 0.80, source="knowledge_base"),
]


# ---------------------------------------------------------------------------
# Contract tests (parametrized over all built-in strategies)
# ---------------------------------------------------------------------------

def _get_builtin_strategies() -> List[RetrievalStrategy]:
    from mojo_memory.retrieval.semantic import SemanticStrategy
    from mojo_memory.retrieval.hybrid import HybridStrategy
    return [SemanticStrategy(), HybridStrategy()]


@pytest.fixture(params=_get_builtin_strategies(), ids=lambda s: s.name)
def strategy(request) -> RetrievalStrategy:
    return request.param


class TestRetrievalStrategyContract:
    def test_is_retrieval_strategy(self, strategy):
        assert isinstance(strategy, RetrievalStrategy)

    def test_has_name(self, strategy):
        assert isinstance(strategy.name, str) and strategy.name

    def test_returns_list_of_scored_results(self, strategy):
        results = strategy.search(QUERY_EMBEDDING, CANDIDATES)
        assert isinstance(results, list)
        assert all(isinstance(r, ScoredResult) for r in results)

    def test_results_sorted_descending(self, strategy):
        results = strategy.search(QUERY_EMBEDDING, CANDIDATES)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_threshold_filters_low_scores(self, strategy):
        results = strategy.search(QUERY_EMBEDDING, CANDIDATES, threshold=0.3)
        # "low relevance" candidate has score ~0.25 — should be excluded
        assert all(r.score >= 0.3 for r in results)

    def test_max_results_respected(self, strategy):
        results = strategy.search(QUERY_EMBEDDING, CANDIDATES, max_results=2)
        assert len(results) <= 2

    def test_empty_candidates_returns_empty(self, strategy):
        results = strategy.search(QUERY_EMBEDDING, [])
        assert results == []

    def test_candidates_without_embeddings_skipped(self, strategy):
        bare = [{"text_content": "no embeddings", "source": "test", "embeddings": {}}]
        results = strategy.search(QUERY_EMBEDDING, bare)
        assert results == []

    def test_content_and_source_preserved(self, strategy):
        results = strategy.search(QUERY_EMBEDDING, CANDIDATES, threshold=0.5)
        sources = {r.source for r in results}
        assert "test" in sources or "knowledge_base" in sources
        for r in results:
            assert isinstance(r.content, str)


# ---------------------------------------------------------------------------
# Strategy registry tests
# ---------------------------------------------------------------------------

class TestStrategyRegistry:
    def test_semantic_registered(self):
        from mojo_memory.retrieval.registry import get_strategy
        s = get_strategy("semantic")
        assert s is not None and s.name == "semantic"

    def test_hybrid_registered(self):
        from mojo_memory.retrieval.registry import get_strategy
        s = get_strategy("hybrid")
        assert s is not None and s.name == "hybrid"

    def test_unknown_returns_none(self):
        from mojo_memory.retrieval.registry import get_strategy
        assert get_strategy("nonexistent") is None

    def test_custom_strategy_registration(self):
        from mojo_memory.retrieval.registry import register_strategy, get_strategy

        class MockStrategy(RetrievalStrategy):
            @property
            def name(self) -> str:
                return "mock"

            def search(self, query_embedding, candidates, *, max_results=10, threshold=0.3):
                return []

        register_strategy("mock", MockStrategy())
        assert get_strategy("mock") is not None
