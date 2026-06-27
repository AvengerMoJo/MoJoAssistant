# Rec 1 — Eval-Driven Consolidation for Dreaming Pipeline

**Source:** autoresearch/EvolveMem integration report (`autoresearch_integration_report.md`)  
**Priority:** HIGH impact / MEDIUM effort  
**Implementing agent:** assign to Popo or Rebecca  
**Spec reviewed:** 2026-06-27 — 4 bugs found and corrected from initial draft  

---

## Goal

Wrap every dreaming cycle in a benchmark-before / benchmark-after loop.  
If retrieval quality degrades beyond a threshold after consolidation, roll back the storage to its pre-dreaming state.  
If quality holds or improves, commit and log the delta.

This applies karpathy/autoresearch's core insight: **eval-driven loops turn batch-and-hope into experimentally validated progress.**

---

## New File to Create

**`app/memory/eval_consolidation.py`**

This is a self-contained module. It must NOT import anything that isn't already in the project.

### Class: `ConsolidationEvaluator`

```python
class ConsolidationEvaluator:
    def __init__(
        self,
        memory_service,          # app.services.hybrid_memory_service.HybridMemoryService
        storage,                 # StorageBackend (may be None) — pass pipeline.storage AFTER role path is set
        query_set_path=None,     # Optional[str] — path to JSON list of probe queries
        role_id="unknown",       # str — scope for search calls
        degradation_threshold=0.03,
    ): ...

    @asynccontextmanager  # NOTE: must be asynccontextmanager, NOT contextmanager
    async def guarded_consolidation(self) -> AsyncGenerator[ConsolidationOutcome, None]:
        """Snapshot → yield → eval → commit or rollback."""

    async def evaluate(self) -> EvalResult:
        """Standalone eval pass (for health checks / dashboards)."""
```

**Important:** `guarded_consolidation` and `evaluate` must be `async` because the eval
step calls `get_context_for_query_async()` (the only version that accepts `role_id`).
Use `from contextlib import asynccontextmanager` and `from typing import AsyncGenerator`.

### Dataclasses

```python
@dataclass
class EvalResult:
    mean_score: float          # mean top-k score across all queries
    query_count: int
    scores: Dict[str, float]   # per-query scores

@dataclass
class ConsolidationOutcome:
    pre: Optional[EvalResult]
    post: Optional[EvalResult]
    committed: bool
    rollback_reason: str = ""

    @property
    def delta(self) -> Optional[float]:
        if self.pre is not None and self.post is not None:
            return self.post.mean_score - self.pre.mean_score
        return None
```

### Eval metric

For each query in the probe set:

1. Call `await memory_service.get_context_for_query_async(query, max_items=TOP_K, role_id=role_id)`  
   — **must use the async version**: the sync `get_context_for_query()` does NOT accept `role_id` and would search the shared user KB instead of the role-scoped KB.
2. Extract score with fallback for both key names in use across the codebase:
   ```python
   score = r.get("relevance_score", r.get("relevance", 0.0))
   ```
   **Why both keys:** `HybridMemoryService` returns `"relevance_score"` but the base
   `MemoryService._get_context_sequential()` returns `"relevance"`. Which path runs
   depends on whether multi-model is enabled.
3. Take mean score across returned items per query.
4. `EvalResult.mean_score` = mean of per-query means.

Rollback condition: `post.mean_score < pre.mean_score - degradation_threshold`  
Special case: if `pre.mean_score == 0.0` (empty KB), always commit.

### Snapshot / rollback

Storage type detection — check both attribute names, as two different backend classes are in use:

```python
def _storage_base_path(self) -> Optional[Path]:
    if self._storage is None:
        return None
    # LocalFileStorageBackend (mojo_memory) uses .base_path
    # JsonFileBackend (dreaming pipeline) uses .storage_path
    base = getattr(self._storage, "base_path", None) \
        or getattr(self._storage, "storage_path", None)
    if base is not None:
        return Path(base)
    logger.warning(
        "[eval_consolidation] storage backend %s has no known path attribute "
        "— rollback disabled",
        type(self._storage).__name__,
    )
    return None
```

Snapshot lifecycle:
```
_take_snapshot()        # copytree base_path → tempdir, before yield
yield outcome
await _evaluate("post")
if rollback:
    _restore_snapshot() # rmtree base_path, copytree tempdir back
_drop_snapshot()        # always, success or failure
```

Snapshot uses `shutil.copytree(base_path, tmp / "snap", dirs_exist_ok=True)`.  
Restore uses `shutil.rmtree(base_path)` then `shutil.copytree(tmp / "snap", base_path)`.

### Query set loading (priority order)

1. `query_set_path` argument (if provided)
2. `~/.memory/config/eval_query_set.json` — JSON list of strings
3. Built-in fallback (5 generic queries):
   ```json
   ["what is the user working on", "recent task results",
    "memory architecture", "role capabilities", "system configuration"]
   ```

---

## Files to Modify

### 1. `app/services/hybrid_memory_service.py`

Add a convenience method so callers don't need to reach into the submodule directly:

```python
async def evaluate_consolidation(
    self,
    query_set: List[str],
    role_id: str = "unknown",
    top_k: int = 5,
) -> float:
    """Return mean top-k relevance score for query_set. Used by ConsolidationEvaluator."""
    scores = []
    for q in query_set:
        # Must use async version — it accepts role_id for role-scoped search
        results = await self.get_context_for_query_async(q, max_items=top_k, role_id=role_id)
        if results:
            scores.append(
                sum(r.get("relevance_score", r.get("relevance", 0.0)) for r in results)
                / len(results)
            )
        else:
            scores.append(0.0)
    return sum(scores) / len(scores) if scores else 0.0
```

Key corrections vs. initial draft:
- `async def` (not sync) — calls async search
- `max_items=` (not `max_results=`) — actual parameter name on the method
- Dual score key fallback `r.get("relevance_score", r.get("relevance", 0.0))`

### 2. `app/scheduler/handlers/dreaming.py`

**Timing constraint (critical):** construct `ConsolidationEvaluator` AFTER `pipeline.storage`
is set to the role-scoped path (line 133), not before. The snapshot must cover the
role-scoped knowledge unit directory, not the default dreams archive.

```python
from app.memory.eval_consolidation import ConsolidationEvaluator

# ... existing code that sets pipeline.storage to role_storage_path ...
# pipeline.storage is now a LocalFileStorageBackend(.../roles/<role_id>/knowledge_units/)

memory_service = ctx._memory_service
role_id = task.config.get("role_id", "unknown")

if memory_service:
    evaluator = ConsolidationEvaluator(
        memory_service=memory_service,
        storage=pipeline.storage,  # role-scoped at this point
        role_id=role_id,
    )
    async with evaluator.guarded_consolidation() as outcome:
        results = await pipeline.process_conversation(
            conversation_id=conversation_id,
            conversation_text=conversation_text,
            metadata=metadata,
        )
else:
    # No memory service — skip eval, run consolidation directly
    outcome = None
    results = await pipeline.process_conversation(
        conversation_id=conversation_id,
        conversation_text=conversation_text,
        metadata=metadata,
    )

# Add eval metrics to task result
if outcome:
    metrics["eval_pre_score"] = outcome.pre.mean_score if outcome.pre else None
    metrics["eval_post_score"] = outcome.post.mean_score if outcome.post else None
    metrics["eval_delta"] = outcome.delta
    metrics["eval_committed"] = outcome.committed
    if not outcome.committed:
        metrics["eval_rollback_reason"] = outcome.rollback_reason
        ctx.log(f"Dreaming rolled back: {outcome.rollback_reason}", "warning")
```

Apply the same wrapper to the `process_document()` call path (same file, ~line 98).

---

## Exact Import Paths (confirmed from codebase audit)

| Symbol | Module / File |
|--------|---------------|
| `HybridMemoryService` (app layer) | `app.services.hybrid_memory_service` |
| `get_context_for_query_async(query, max_items, role_id)` | `mojo_memory.services.hybrid_memory_service` line 295 — async, role_id supported |
| `get_context_for_query(query, max_items)` | line 257 — sync, NO role_id param |
| `LocalFileStorageBackend` (`.base_path`) | `mojo_memory.storage.local_fs_backend` |
| `JsonFileBackend` (`.storage_path`) | `dreaming.storage.json_backend` (submodule) |
| `DreamingHandler` | `app.scheduler.handlers.dreaming` |
| `ExecutorContext._memory_service` | `app.scheduler.executor_registry` line 91 |
| `pipeline.storage` set to role path | `app/scheduler/handlers/dreaming.py` line 133 |
| `get_memory_subpath` | `app.config.paths` |

---

## Success Criteria

1. Unit test: mock `get_context_for_query_async` returns lower scores on second call → `outcome.committed == False`, storage dir restored to pre-state
2. Unit test: improved scores → `outcome.committed == True`
3. Unit test: `pre.mean_score == 0.0` (empty KB) → always commits regardless of post score
4. Unit test: `memory_service=None` → dreaming runs unchanged, no crash
5. Integration test: full dreaming task with `mode=conversation` and a role-scoped pipeline produces `eval_pre_score`, `eval_post_score`, `eval_delta`, `eval_committed` in task metrics
6. `~/.memory/config/eval_query_set.json` overrides the built-in query set without code changes
7. `_storage_base_path()` correctly resolves both `LocalFileStorageBackend.base_path` and `JsonFileBackend.storage_path`

---

## What NOT to do

- Do not add this to the submodule (`dreaming-memory-pipeline`). The eval wrapper belongs in the app layer.
- Do not use `contextmanager` — use `asynccontextmanager`. The eval step is async.
- Do not call `get_context_for_query()` (sync) — it ignores `role_id` and searches the shared KB.
- Do not use `max_results=` — the actual kwarg is `max_items=`.
- Do not construct the evaluator before `pipeline.storage` is set to the role path — the snapshot would cover the wrong directory.
- Do not rollback on exceptions — only on quality degradation. Exceptions propagate normally.
