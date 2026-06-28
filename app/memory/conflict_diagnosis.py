"""Conflict Diagnosis for Knowledge Bases.

Scans for semantic contradictions, stale units, and knowledge gaps.
Inspired by EvolveMem's diagnosis module — the "sense" layer that
identifies what needs updating before acting.

Usage:
    from app.memory.conflict_diagnosis import ConflictDiagnoser

    diagnoser = ConflictDiagnoser(memory_service, role_id="rebecca")
    report = diagnoser.diagnose(query_set=["topic1", "topic2"])
    if not report.healthy:
        print(report.summary())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class KnowledgeGap:
    """A query where the KB returned nothing or very low confidence results."""
    query: str
    top_score: float       # relevance_score of best result, or 0.0 if no results
    result_count: int


@dataclass
class ConflictReport:
    """A diagnosed conflict between two knowledge units."""
    unit_a_id: str
    unit_b_id: str
    unit_a_text: str
    unit_b_text: str
    query: str
    score_a: float
    score_b: float
    similarity: float      # cosine similarity (0=unrelated, 1=identical)
    conflict_type: str     # "contradiction", "staleness", "redundancy"
    reason: str
    severity: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unit_a_id": self.unit_a_id,
            "unit_b_id": self.unit_b_id,
            "unit_a_text": self.unit_a_text[:200],
            "unit_b_text": self.unit_b_text[:200],
            "query": self.query,
            "score_a": self.score_a,
            "score_b": self.score_b,
            "similarity": self.similarity,
            "conflict_type": self.conflict_type,
            "reason": self.reason,
            "severity": self.severity,
        }


@dataclass
class DiagnosisSummary:
    """Summary of a full diagnosis pass."""
    role_id: str
    total_queries: int
    total_conflicts: int
    contradictions: int
    staleness: int
    redundancy: int
    conflicts: List[ConflictReport] = field(default_factory=list)
    gaps: List[KnowledgeGap] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return self.total_conflicts == 0 and len(self.gaps) == 0

    def summary(self) -> str:
        return (
            f"{self.total_conflicts} conflict(s) "
            f"({self.contradictions} contradiction, {self.staleness} stale, "
            f"{self.redundancy} redundant), "
            f"{len(self.gaps)} gap(s) across {self.total_queries} queries"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role_id": self.role_id,
            "total_queries": self.total_queries,
            "total_conflicts": self.total_conflicts,
            "contradictions": self.contradictions,
            "staleness": self.staleness,
            "redundancy": self.redundancy,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "gaps": [
                {"query": g.query, "top_score": g.top_score, "result_count": g.result_count}
                for g in self.gaps
            ],
            "healthy": self.healthy,
        }


# ---------------------------------------------------------------------------
# Diagnoser
# ---------------------------------------------------------------------------

class ConflictDiagnoser:
    """Scans the knowledge base for contradictions, staleness, and gaps.

    For each query:
    1. Retrieve top-k results from memory_service
    2. Check for low-confidence results → KnowledgeGap
    3. Embed all result texts in one batch (one backend instance per query)
    4. Pairwise cosine similarity:
       - high similarity + different content → contradiction
       - very high similarity → redundancy
       - similar content + large timestamp gap → staleness
    """

    LOW_CONFIDENCE_THRESHOLD = 0.40
    CONTRADICTION_THRESHOLD = 0.85   # cosine sim above this = same topic
    REDUNDANCY_THRESHOLD = 0.97      # cosine sim above this = near-duplicate

    def __init__(
        self,
        memory_service: Any,
        role_id: str = "unknown",
        top_k: int = 10,
    ):
        self._memory_service = memory_service
        self._role_id = role_id
        self._top_k = top_k

    def diagnose(self, query_set: Optional[List[str]] = None) -> DiagnosisSummary:
        """Run diagnosis across all queries. Returns a typed DiagnosisSummary."""
        if not query_set:
            query_set = [
                "user preferences and settings",
                "recent project decisions",
                "technical architecture choices",
                "meeting outcomes and action items",
                "bug reports and fixes",
            ]

        all_conflicts: List[ConflictReport] = []
        all_gaps: List[KnowledgeGap] = []
        contradictions = staleness = redundancy = 0

        for query in query_set:
            conflicts, gaps = self._diagnose_query(query)
            all_gaps.extend(gaps)
            for c in conflicts:
                if c.conflict_type == "contradiction":
                    contradictions += 1
                elif c.conflict_type == "staleness":
                    staleness += 1
                elif c.conflict_type == "redundancy":
                    redundancy += 1
            all_conflicts.extend(conflicts)

        return DiagnosisSummary(
            role_id=self._role_id,
            total_queries=len(query_set),
            total_conflicts=len(all_conflicts),
            contradictions=contradictions,
            staleness=staleness,
            redundancy=redundancy,
            conflicts=all_conflicts,
            gaps=all_gaps,
        )

    def _diagnose_query(
        self, query: str
    ) -> Tuple[List[ConflictReport], List[KnowledgeGap]]:
        """Diagnose a single query. Returns (conflicts, gaps)."""
        if not self._memory_service:
            return [], []

        try:
            results = self._memory_service.get_context_for_query(
                query, max_items=self._top_k
            )
        except Exception as e:
            logger.warning("Diagnosis query failed for '%s': %s", query, e)
            return [], []

        gaps: List[KnowledgeGap] = []
        if not results:
            gaps.append(KnowledgeGap(query=query, top_score=0.0, result_count=0))
            return [], gaps

        top_score = results[0].get("relevance_score", results[0].get("relevance", 0.0))
        if top_score < self.LOW_CONFIDENCE_THRESHOLD:
            gaps.append(KnowledgeGap(
                query=query, top_score=top_score, result_count=len(results)
            ))

        if len(results) < 2:
            return [], gaps

        # Embed all result texts in one pass with a single backend instance.
        # This avoids creating a new model per pair (which would re-load weights
        # for each of the O(n²) comparisons).
        texts = [r.get("content", "")[:500] for r in results]
        embeddings = self._embed_texts(texts)

        conflicts: List[ConflictReport] = []
        seen_pairs: set = set()
        for i, unit_a in enumerate(results):
            for j, unit_b in enumerate(results[i + 1:], i + 1):
                pair_key = (i, j)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                conflict = self._check_pair(
                    query, unit_a, unit_b, embeddings[i], embeddings[j]
                )
                if conflict:
                    conflicts.append(conflict)

        return conflicts, gaps

    def _embed_texts(
        self, texts: List[str]
    ) -> List[Optional[List[float]]]:
        """Embed a batch of texts using EmbeddingPool's primary resource.

        Creates one SimpleEmbedding instance for the whole batch so model
        weights are loaded once, not per call.  Returns None per entry on failure.
        """
        try:
            from app.memory.embedding_pool import get_embedding_pool
            from app.memory.simplified_embeddings import SimpleEmbedding

            pool = get_embedding_pool()
            resource = pool.acquire()
            if resource is None:
                return [None] * len(texts)

            emb = SimpleEmbedding(
                backend=resource.backend,
                model_name=resource.model_name,
                device=resource.device or "cpu",
            )
            return [emb.get_text_embedding(t) for t in texts]
        except Exception as e:
            logger.debug("Batch embedding failed, skipping cosine checks: %s", e)
            return [None] * len(texts)

    def _check_pair(
        self,
        query: str,
        unit_a: Dict[str, Any],
        unit_b: Dict[str, Any],
        emb_a: Optional[List[float]],
        emb_b: Optional[List[float]],
    ) -> Optional[ConflictReport]:
        """Check a pair of knowledge units for conflict."""
        text_a = unit_a.get("content", "")
        text_b = unit_b.get("content", "")
        score_a = unit_a.get("relevance_score", unit_a.get("relevance", 0.0))
        score_b = unit_b.get("relevance_score", unit_b.get("relevance", 0.0))
        id_a = str(unit_a.get("id", unit_a.get("doc_id", hash(text_a))))
        id_b = str(unit_b.get("id", unit_b.get("doc_id", hash(text_b))))

        if not text_a or not text_b:
            return None

        # Compute cosine similarity; fall back to Jaccard if no embeddings.
        if emb_a and emb_b:
            sim = _cosine_sim(emb_a, emb_b)
        else:
            sim = _jaccard_sim(text_a, text_b)

        # Redundancy: near-identical content (catches duplicates)
        if sim >= self.REDUNDANCY_THRESHOLD and text_a.strip() != text_b.strip():
            return ConflictReport(
                unit_a_id=id_a, unit_b_id=id_b,
                unit_a_text=text_a, unit_b_text=text_b,
                query=query, score_a=score_a, score_b=score_b,
                similarity=sim,
                conflict_type="redundancy",
                reason=f"Near-duplicate units (similarity={sim:.2f}) — consider MERGE_UNITS",
                severity="low",
            )

        # Contradiction: high relevance + high similarity but different content
        # Same topic, both retrieved, but content differs → potential conflict
        if (score_a > 0.5 and score_b > 0.5
                and sim >= self.CONTRADICTION_THRESHOLD
                and text_a.strip() != text_b.strip()):
            return ConflictReport(
                unit_a_id=id_a, unit_b_id=id_b,
                unit_a_text=text_a, unit_b_text=text_b,
                query=query, score_a=score_a, score_b=score_b,
                similarity=sim,
                conflict_type="contradiction",
                reason=(
                    f"Both units highly relevant ({score_a:.2f}, {score_b:.2f}) and "
                    f"semantically similar ({sim:.2f}) but content differs — "
                    f"likely contradictory facts about '{query}'"
                ),
                severity="high",
            )

        # Staleness: similar content (same topic) but large timestamp gap
        if sim >= 0.7:
            ts_a = unit_a.get("created_at", "")
            ts_b = unit_b.get("created_at", "")
            if ts_a and ts_b:
                try:
                    from datetime import datetime
                    dt_a = datetime.fromisoformat(ts_a.replace("Z", "+00:00"))
                    dt_b = datetime.fromisoformat(ts_b.replace("Z", "+00:00"))
                    days_diff = abs((dt_a - dt_b).days)
                    if days_diff > 30:
                        return ConflictReport(
                            unit_a_id=id_a, unit_b_id=id_b,
                            unit_a_text=text_a, unit_b_text=text_b,
                            query=query, score_a=score_a, score_b=score_b,
                            similarity=sim,
                            conflict_type="staleness",
                            reason=(
                                f"Similar content (sim={sim:.2f}) but {days_diff} days apart "
                                f"— older unit may be stale, consider RETIRE_STALE"
                            ),
                            severity="medium",
                        )
                except Exception:
                    pass

        return None


# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------

def _cosine_sim(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _jaccard_sim(text_a: str, text_b: str) -> float:
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)
