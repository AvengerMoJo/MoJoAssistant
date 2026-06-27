"""Eval-Driven Consolidation for Dreaming Pipeline.

Wraps every dreaming cycle in a benchmark-before/benchmark-after loop.
If retrieval quality degrades beyond a threshold after consolidation,
rolls back the storage to its pre-dreaming state.

Applies karpathy/autoresearch's core insight:
eval-driven loops turn batch-and-hope into experimentally validated progress.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

# Default probe queries for eval
_DEFAULT_QUERIES = [
    "what is the user working on",
    "recent task results",
    "memory architecture",
    "role capabilities",
    "system configuration",
]


@dataclass
class EvalResult:
    """Result of an evaluation pass."""
    mean_score: float          # mean top-k relevance_score across all queries
    query_count: int
    scores: Dict[str, float]   # per-query scores

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mean_score": self.mean_score,
            "query_count": self.query_count,
            "scores": self.scores,
        }


@dataclass
class ConsolidationOutcome:
    """Result of a guarded consolidation."""
    pre: Optional[EvalResult]
    post: Optional[EvalResult]
    committed: bool
    rollback_reason: str = ""

    @property
    def delta(self) -> Optional[float]:
        """Post - pre mean score. None if either is missing."""
        if self.pre and self.post:
            return self.post.mean_score - self.pre.mean_score
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pre": self.pre.to_dict() if self.pre else None,
            "post": self.post.to_dict() if self.post else None,
            "committed": self.committed,
            "rollback_reason": self.rollback_reason,
            "delta": self.delta,
        }


class ConsolidationEvaluator:
    """Evaluates dreaming consolidation quality and rolls back on degradation.

    Usage:
        evaluator = ConsolidationEvaluator(
            memory_service=memory_service,
            storage=pipeline.storage,
            role_id="rebecca",
        )
        with evaluator.guarded_consolidation() as outcome:
            await pipeline.process_conversation(...)

        # outcome.committed tells you if the dreaming stuck
    """

    def __init__(
        self,
        memory_service: Any,
        storage: Any = None,
        query_set_path: Optional[str] = None,
        role_id: str = "unknown",
        degradation_threshold: float = 0.03,
    ):
        self._memory_service = memory_service
        self._storage = storage
        self._role_id = role_id
        self._threshold = degradation_threshold
        self._query_set = self._load_queries(query_set_path)
        self._snapshot_path: Optional[Path] = None

    def _load_queries(self, path: Optional[str]) -> List[str]:
        """Load probe queries from path, config, or built-in fallback."""
        # 1. Explicit path
        if path:
            try:
                return json.loads(Path(path).read_text())
            except Exception as e:
                logger.warning(f"Failed to load query set from {path}: {e}")

        # 2. User config
        config_path = Path.home() / ".memory" / "config" / "eval_query_set.json"
        if config_path.exists():
            try:
                return json.loads(config_path.read_text())
            except Exception as e:
                logger.warning(f"Failed to load query set from {config_path}: {e}")

        # 3. Built-in fallback
        return list(_DEFAULT_QUERIES)

    def evaluate(self) -> EvalResult:
        """Standalone eval pass (for health checks / dashboards)."""
        return self._evaluate_queries()

    def _evaluate_queries(self) -> EvalResult:
        """Run probe queries and compute mean relevance score."""
        if not self._memory_service:
            return EvalResult(mean_score=0.0, query_count=0, scores={})

        scores: Dict[str, float] = {}
        for query in self._query_set:
            try:
                results = self._memory_service.get_context_for_query(
                    query, max_results=5, role_id=self._role_id
                )
                if results:
                    query_score = sum(
                        r.get("relevance_score", 0.0) for r in results
                    ) / len(results)
                else:
                    query_score = 0.0
                scores[query] = query_score
            except Exception as e:
                logger.warning(f"Eval query failed for '{query}': {e}")
                scores[query] = 0.0

        mean_score = sum(scores.values()) / len(scores) if scores else 0.0
        return EvalResult(
            mean_score=round(mean_score, 4),
            query_count=len(scores),
            scores=scores,
        )

    def _take_snapshot(self) -> Optional[Path]:
        """Snapshot storage before dreaming. Returns snapshot path or None."""
        if not self._storage:
            logger.warning("No storage provided — snapshot disabled")
            return None

        # LocalFileStorageBackend has .base_path
        base_path = getattr(self._storage, "base_path", None)
        if not base_path or not isinstance(base_path, Path):
            logger.warning("Storage has no .base_path — snapshot not supported")
            return None

        if not base_path.exists():
            return None

        snapshot_dir = Path(tempfile.mkdtemp(prefix="mojo_eval_snapshot_"))
        try:
            shutil.copytree(str(base_path), str(snapshot_dir / "snapshot"), dirs_exist_ok=True)
            logger.info(f"Snapshot taken: {snapshot_dir}")
            return snapshot_dir
        except Exception as e:
            logger.warning(f"Snapshot failed: {e}")
            return None

    def _restore_snapshot(self, snapshot_path: Path) -> bool:
        """Restore storage from snapshot."""
        if not self._storage or not snapshot_path:
            return False

        base_path = getattr(self._storage, "base_path", None)
        if not base_path:
            return False

        snapshot_data = snapshot_path / "snapshot"
        if not snapshot_data.exists():
            logger.warning(f"Snapshot data not found at {snapshot_data}")
            return False

        try:
            if base_path.exists():
                shutil.rmtree(str(base_path))
            shutil.copytree(str(snapshot_data), str(base_path))
            logger.info(f"Snapshot restored from {snapshot_path}")
            return True
        except Exception as e:
            logger.warning(f"Snapshot restore failed: {e}")
            return False

    def _drop_snapshot(self, snapshot_path: Optional[Path]) -> None:
        """Clean up snapshot directory."""
        if snapshot_path and snapshot_path.exists():
            try:
                shutil.rmtree(str(snapshot_path))
                logger.debug(f"Snapshot dropped: {snapshot_path}")
            except Exception as e:
                logger.warning(f"Snapshot cleanup failed: {e}")

    @contextmanager
    def guarded_consolidation(self) -> Generator[ConsolidationOutcome, None, None]:
        """Snapshot → yield → eval → commit or rollback.

        Usage:
            with evaluator.guarded_consolidation() as outcome:
                await pipeline.process_conversation(...)

            if not outcome.committed:
                logger.warning(f"Dreaming rolled back: {outcome.rollback_reason}")
        """
        outcome = ConsolidationOutcome(pre=None, post=None, committed=True)

        # Skip eval if no memory service
        if not self._memory_service:
            logger.warning("No memory service — skipping eval, committing unconditionally")
            yield outcome
            return

        # Pre-eval
        try:
            outcome.pre = self._evaluate_queries()
            logger.info(f"Pre-consolidation score: {outcome.pre.mean_score}")
        except Exception as e:
            logger.warning(f"Pre-eval failed: {e}")
            yield outcome
            return

        # Snapshot
        self._snapshot_path = self._take_snapshot()

        try:
            # Yield control to the dreaming pipeline
            yield outcome

            # Post-eval
            try:
                outcome.post = self._evaluate_queries()
                logger.info(f"Post-consolidation score: {outcome.post.mean_score}")
            except Exception as e:
                logger.warning(f"Post-eval failed: {e}")
                outcome.committed = True  # Don't rollback on eval failure
                return

            # Check for degradation
            if outcome.pre.mean_score == 0.0:
                # Empty KB — any non-empty post passes
                outcome.committed = True
                logger.info("Empty KB pre-dreaming — committing unconditionally")
            elif outcome.post.mean_score < outcome.pre.mean_score - self._threshold:
                # Degradation detected — rollback
                outcome.committed = False
                outcome.rollback_reason = (
                    f"Quality degraded: {outcome.pre.mean_score} → {outcome.post.mean_score} "
                    f"(delta={outcome.delta:.4f}, threshold={self._threshold})"
                )
                logger.warning(f"Dreaming rolled back: {outcome.rollback_reason}")

                if self._snapshot_path:
                    if self._restore_snapshot(self._snapshot_path):
                        logger.info("Storage restored to pre-dreaming state")
                    else:
                        logger.error("Snapshot restore failed — storage may be inconsistent")
            else:
                # Quality held or improved — commit
                outcome.committed = True
                logger.info(
                    f"Dreaming committed: {outcome.pre.mean_score} → {outcome.post.mean_score} "
                    f"(delta={outcome.delta:.4f})"
                )

        finally:
            # Always clean up snapshot
            self._drop_snapshot(self._snapshot_path)
            self._snapshot_path = None
