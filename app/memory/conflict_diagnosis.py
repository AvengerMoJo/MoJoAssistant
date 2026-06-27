"""Conflict Diagnosis for Knowledge Bases.

Scans for semantic contradictions and stale knowledge units.
Inspired by EvolveMem's diagnosis module — the "sense" layer
that identifies what needs updating before acting.

Usage:
    from app.memory.conflict_diagnosis import ConflictDiagnoser, ConflictReport

    diagnoser = ConflictDiagnoser(memory_service, role_id="rebecca")
    conflicts = diagnoser.diagnose(query_set=["topic1", "topic2"])
    for c in conflicts:
        print(f"Conflict: {c.unit_a_id} vs {c.unit_b_id} — {c.reason}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConflictReport:
    """A diagnosed conflict between two knowledge units."""
    unit_a_id: str
    unit_b_id: str
    unit_a_text: str
    unit_b_text: str
    query: str              # the query that surfaced both units
    score_a: float          # relevance score of unit A
    score_b: float          # relevance score of unit B
    distance: float         # embedding distance between A and B (0=identical, 1=unrelated)
    conflict_type: str      # "contradiction", "staleness", "redundancy"
    reason: str             # human-readable explanation
    severity: str = "medium"  # low, medium, high

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unit_a_id": self.unit_a_id,
            "unit_b_id": self.unit_b_id,
            "unit_a_text": self.unit_a_text[:200],
            "unit_b_text": self.unit_b_text[:200],
            "query": self.query,
            "score_a": self.score_a,
            "score_b": self.score_b,
            "distance": self.distance,
            "conflict_type": self.conflict_type,
            "reason": self.reason,
            "severity": self.severity,
        }


@dataclass
class DiagnosisSummary:
    """Summary of a diagnosis pass."""
    total_queries: int
    total_conflicts: int
    contradictions: int
    staleness: int
    redundancy: int
    conflicts: List[ConflictReport] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_queries": self.total_queries,
            "total_conflicts": self.total_conflicts,
            "contradictions": self.contradictions,
            "staleness": self.staleness,
            "redundancy": self.redundancy,
            "conflicts": [c.to_dict() for c in self.conflicts],
        }


class ConflictDiagnoser:
    """Scans knowledge base for contradictions and stale knowledge.

    For each query in the probe set:
    1. Retrieve top-k knowledge units
    2. Check for pairs with high relevance but low semantic similarity
       (contradictions: same topic, different facts)
    3. Check for pairs with high similarity but different timestamps
       (staleness: old unit superseded by new)
    4. Check for pairs with very high similarity
       (redundancy: duplicate knowledge)
    """

    def __init__(
        self,
        memory_service: Any,
        role_id: str = "unknown",
        top_k: int = 10,
        contradiction_threshold: float = 0.3,
        redundancy_threshold: float = 0.95,
    ):
        self._memory_service = memory_service
        self._role_id = role_id
        self._top_k = top_k
        self._contradiction_threshold = contradiction_threshold
        self._redundancy_threshold = redundancy_threshold

    def diagnose(self, query_set: Optional[List[str]] = None) -> DiagnosisSummary:
        """Run diagnosis across a set of queries.

        Args:
            query_set: Queries to probe. If None, uses default set.

        Returns:
            DiagnosisSummary with all detected conflicts.
        """
        if not query_set:
            query_set = [
                "user preferences and settings",
                "recent project decisions",
                "technical architecture choices",
                "meeting outcomes and action items",
                "bug reports and fixes",
            ]

        all_conflicts: List[ConflictReport] = []
        contradictions = 0
        staleness = 0
        redundancy = 0

        for query in query_set:
            conflicts = self._diagnose_query(query)
            for c in conflicts:
                if c.conflict_type == "contradiction":
                    contradictions += 1
                elif c.conflict_type == "staleness":
                    staleness += 1
                elif c.conflict_type == "redundancy":
                    redundancy += 1
            all_conflicts.extend(conflicts)

        return DiagnosisSummary(
            total_queries=len(query_set),
            total_conflicts=len(all_conflicts),
            contradictions=contradictions,
            staleness=staleness,
            redundancy=redundancy,
            conflicts=all_conflicts,
        )

    def _diagnose_query(self, query: str) -> List[ConflictReport]:
        """Diagnose conflicts for a single query."""
        if not self._memory_service:
            return []

        try:
            results = self._memory_service.get_context_for_query(
                query, max_results=self._top_k, role_id=self._role_id
            )
        except Exception as e:
            logger.warning(f"Diagnosis query failed for '{query}': {e}")
            return []

        if not results or len(results) < 2:
            return []

        conflicts = []
        seen_pairs = set()

        for i, unit_a in enumerate(results):
            for j, unit_b in enumerate(results[i + 1:], i + 1):
                pair_key = tuple(sorted([i, j]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                conflict = self._check_pair(query, unit_a, unit_b)
                if conflict:
                    conflicts.append(conflict)

        return conflicts

    def _check_pair(
        self, query: str, unit_a: Dict[str, Any], unit_b: Dict[str, Any]
    ) -> Optional[ConflictReport]:
        """Check a pair of knowledge units for conflicts."""
        text_a = unit_a.get("content", "")
        text_b = unit_b.get("content", "")
        score_a = unit_a.get("relevance_score", 0.0)
        score_b = unit_b.get("relevance_score", 0.0)
        id_a = unit_a.get("id", unit_a.get("doc_id", f"unit_{hash(text_a)}"))
        id_b = unit_b.get("id", unit_b.get("doc_id", f"unit_{hash(text_b)}"))

        if not text_a or not text_b:
            return None

        # Compute simple text similarity (word overlap)
        distance = self._compute_distance(text_a, text_b)

        # Check for contradictions: high relevance, low similarity
        # (same query returns different facts)
        if score_a > 0.5 and score_b > 0.5 and distance > self._contradiction_threshold:
            return ConflictReport(
                unit_a_id=str(id_a),
                unit_b_id=str(id_b),
                unit_a_text=text_a,
                unit_b_text=text_b,
                query=query,
                score_a=score_a,
                score_b=score_b,
                distance=distance,
                conflict_type="contradiction",
                reason=f"Both units have high relevance ({score_a:.2f}, {score_b:.2f}) but low similarity ({distance:.2f}) — likely contradictory facts about '{query}'",
                severity="high",
            )

        # Check for redundancy: very high similarity
        if distance < (1.0 - self._redundancy_threshold):
            return ConflictReport(
                unit_a_id=str(id_a),
                unit_b_id=str(id_b),
                unit_a_text=text_a,
                unit_b_text=text_b,
                query=query,
                score_a=score_a,
                score_b=score_b,
                distance=distance,
                conflict_type="redundancy",
                reason=f"Units are near-duplicates (similarity={1.0 - distance:.2f}) — consider merging",
                severity="low",
            )

        # Check for staleness: similar content, different timestamps
        ts_a = unit_a.get("created_at", "")
        ts_b = unit_b.get("created_at", "")
        if ts_a and ts_b and distance < 0.2:
            try:
                from datetime import datetime
                dt_a = datetime.fromisoformat(ts_a.replace("Z", "+00:00"))
                dt_b = datetime.fromisoformat(ts_b.replace("Z", "+00:00"))
                days_diff = abs((dt_a - dt_b).days)
                if days_diff > 30:
                    return ConflictReport(
                        unit_a_id=str(id_a),
                        unit_b_id=str(id_b),
                        unit_a_text=text_a,
                        unit_b_text=text_b,
                        query=query,
                        score_a=score_a,
                        score_b=score_b,
                        distance=distance,
                        conflict_type="staleness",
                        reason=f"Similar content but {days_diff} days apart — older unit may be stale",
                        severity="medium",
                    )
            except Exception:
                pass

        return None

    def _compute_distance(self, text_a: str, text_b: str) -> float:
        """Compute semantic distance between two texts (0=identical, 1=unrelated).

        Uses word overlap (Jaccard distance) as a fast proxy.
        For production, replace with embedding cosine distance.
        """
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a or not words_b:
            return 1.0
        intersection = words_a & words_b
        union = words_a | words_b
        similarity = len(intersection) / len(union)
        return 1.0 - similarity
