# Rec 3 — Conflict Diagnosis in EmbeddingPool

**Source:** autoresearch/EvolveMem integration report (`autoresearch_integration_report.md`)  
**Priority:** MEDIUM-HIGH impact / LOW-MEDIUM effort (~150 lines, 1 file)  
**Implementing agent:** assign to Popo or Rebecca  

---

## Goal

Add a diagnosis pass to `EmbeddingPool` that identifies semantic contradictions and low-confidence retrievals in the knowledge base.

This is EvolveMem's "diagnosis module" — the sensing layer that feeds Recommendations 1 and 2.  
Without it, memory degradation is silent. With it, the system can proactively flag stale or contradictory units before they corrupt retrieval quality.

---

## New Method to Add

**File:** `app/memory/embedding_pool.py`  
**Class:** `EmbeddingPool`

### `diagnose_conflicts()`

```python
def diagnose_conflicts(
    self,
    memory_service,               # HybridMemoryService
    query_set: List[str],
    role_id: str = "unknown",
    top_k: int = 5,
    contradiction_threshold: float = 0.85,  # cosine sim above this = likely duplicate/contradiction
    low_confidence_threshold: float = 0.40, # top-1 score below this = knowledge gap
) -> "DiagnosisReport":
    """
    Scan for semantic contradictions and low-confidence retrievals.

    For each query in query_set:
    1. Retrieve top-k results from memory_service
    2. Embed the top-k result texts using the pool's primary resource
    3. Compute pairwise cosine similarity between result embeddings
    4. Pairs with similarity > contradiction_threshold AND different content
       are flagged as potential contradictions
    5. Queries where top-1 relevance_score < low_confidence_threshold
       are flagged as knowledge gaps

    Returns a DiagnosisReport listing contradictions and gaps.
    """
```

### New Dataclasses (add to `app/memory/embedding_pool.py`)

```python
@dataclass
class ConflictPair:
    query: str               # the query that surfaced both units
    unit_a_content: str      # truncated to 200 chars
    unit_b_content: str
    similarity: float        # cosine similarity between their embeddings
    source_a: str            # "knowledge_base", "conversation", etc.
    source_b: str

@dataclass
class KnowledgeGap:
    query: str
    top_score: float         # relevance_score of best result (or 0.0 if no results)
    result_count: int

@dataclass
class DiagnosisReport:
    role_id: str
    query_count: int
    conflicts: List[ConflictPair]
    gaps: List[KnowledgeGap]
    generated_at: str        # ISO 8601
    primary_resource_id: str # which embedding resource was used

    @property
    def healthy(self) -> bool:
        return len(self.conflicts) == 0 and len(self.gaps) == 0

    def summary(self) -> str:
        return (
            f"{len(self.conflicts)} conflict(s), {len(self.gaps)} gap(s) "
            f"across {self.query_count} queries"
        )
```

---

## Implementation Detail

### Cosine similarity helper (pure Python, no new deps)

```python
def _cosine_sim(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
```

### Contradiction detection logic

```python
for query in query_set:
    results = memory_service.get_context_for_query(query, max_results=top_k, role_id=role_id)
    if not results:
        gaps.append(KnowledgeGap(query=query, top_score=0.0, result_count=0))
        continue

    top_score = results[0].get("relevance_score", 0.0)
    if top_score < low_confidence_threshold:
        gaps.append(KnowledgeGap(query=query, top_score=top_score, result_count=len(results)))

    # Embed each result text via the pool's primary resource
    embeddings = []
    for r in results:
        text = r.get("content", "")[:500]  # truncate to avoid slow embeds
        emb = self._embed_text_for_diagnosis(text)
        embeddings.append(emb)

    # Pairwise conflict check
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            if embeddings[i] is None or embeddings[j] is None:
                continue
            sim = _cosine_sim(embeddings[i], embeddings[j])
            if sim >= contradiction_threshold:
                # High similarity + different content = contradiction candidate
                if results[i]["content"][:100] != results[j]["content"][:100]:
                    conflicts.append(ConflictPair(
                        query=query,
                        unit_a_content=results[i]["content"][:200],
                        unit_b_content=results[j]["content"][:200],
                        similarity=sim,
                        source_a=results[i].get("source", ""),
                        source_b=results[j].get("source", ""),
                    ))
```

### `_embed_text_for_diagnosis()` private helper

```python
def _embed_text_for_diagnosis(self, text: str) -> Optional[List[float]]:
    """Embed text using the pool's primary available resource. Returns None on failure."""
    resource = self.acquire()   # existing EmbeddingPool.acquire() method
    if resource is None:
        return None
    try:
        # Import the pool-aware SimpleEmbedding to avoid direct backend access
        from app.memory.simplified_embeddings import SimpleEmbedding
        emb = SimpleEmbedding(
            backend=resource.backend,
            model_name=resource.model_name,
            device=resource.device,
        )
        return emb.get_text_embedding(text)
    except Exception as exc:
        logger.warning("[embedding_pool] diagnosis embed failed: %s", exc)
        return None
```

---

## Integration Points

### Called by DreamingHandler (optional, post-Rec-1)

After eval-driven consolidation (Rec 1), optionally run diagnosis and store report in task metrics:

```python
# In app/scheduler/handlers/dreaming.py, after consolidation commit:
if outcome.committed and memory_service:
    report = pool.diagnose_conflicts(memory_service, query_set, role_id=role_id)
    metrics["diagnosis_conflicts"] = len(report.conflicts)
    metrics["diagnosis_gaps"] = len(report.gaps)
    if not report.healthy:
        ctx.log(f"Diagnosis: {report.summary()}", "warning")
```

### Exposed via MCP health endpoint (future)

`DiagnosisReport.summary()` can feed the dashboard's memory health widget.  
No MCP tool change needed now — keep this as a library method.

---

## Exact Import Paths (confirmed from codebase audit)

| Symbol | Module |
|--------|--------|
| `EmbeddingPool` | `app.memory.embedding_pool` |
| `EmbeddingResource` | `app.memory.embedding_pool` |
| `EmbeddingPool.acquire()` | `app/memory/embedding_pool.py` line 181 |
| `EmbeddingPool.mark_failed()` | `app/memory/embedding_pool.py` line 245 |
| `SimpleEmbedding.get_text_embedding()` | `app.memory.simplified_embeddings` |
| `HybridMemoryService.get_context_for_query()` | `submodules/dreaming-memory-pipeline/src/mojo_memory/services/hybrid_memory_service.py` line 257 |

---

## Success Criteria

1. `diagnose_conflicts(memory_service, ["test query"], role_id="popo")` returns a `DiagnosisReport` without crashing even if the KB is empty
2. Two units with >0.85 cosine similarity but different content → appear in `report.conflicts`
3. A query with no matching knowledge units → appears in `report.gaps`
4. `report.healthy` is `True` when no conflicts and no gaps
5. `_embed_text_for_diagnosis()` returns `None` gracefully if pool has no available resources
6. No new dependencies — uses only `app.memory.simplified_embeddings` and `app.memory.embedding_pool` (both already in the project)

---

## What NOT to do

- Do not run diagnosis on every search call — it's an expensive scan, run it post-dreaming or on demand
- Do not block dreaming if diagnosis fails — wrap in try/except, log, continue
- Do not deduplicate conflicts (same pair may appear for multiple queries — that's signal, not noise)
