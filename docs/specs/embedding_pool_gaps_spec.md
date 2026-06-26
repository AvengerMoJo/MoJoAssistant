# Embedding Pool Gaps — Fix Spec

**Date:** 2026-06-26
**Status:** Draft
**Scope:** `app/memory/embedding_pool.py`, `app/memory/simplified_embeddings.py`, related config and tests

---

## Gap 1: No Auto-Recovery

**Problem:** `mark_failed` is permanent. A transient network error disables a backend forever until manual `mark_available`.

**Fix:** Add `failed_at: float` to `EmbeddingResource`. In `acquire()`, skip resources where `status == "failed"` AND `time.time() - failed_at < recovery_ttl_seconds`. Default TTL: 300s (5 min). After TTL, the resource becomes eligible again.

**Files:** `app/memory/embedding_pool.py` (EmbeddingResource dataclass, acquire method)

---

## Gap 2: Dimension Mismatch on Failover

**Problem:** Backend A (1024-dim) fails → fallback to Backend B (384-dim). Stored vectors are now incompatible. Qdrant collection expects one dimension.

**Fix:** In `acquire_with_fallback()`, filter candidates to those matching the primary's `embedding_dim`. Log a warning if a backend is skipped due to dim mismatch. Add `strict_dim: bool = True` param to `EmbeddingPool.__init__()`.

**Files:** `app/memory/embedding_pool.py` (acquire_with_fallback)

---

## Gap 3: Missing `request_format` / `api_key_env` Fields

**Problem:** Leon's PR added `request_format: "openai"` and `api_key_env` to `LocalServerBackend`, but `EmbeddingResource` doesn't have these fields. Pool can't pass them through.

**Fix:** Add `request_format: str = "legacy"` and `api_key_env: Optional[str] = None` to `EmbeddingResource`. Pass through in `_parse_resource()` and `_switch_backend()`.

**Files:** `app/memory/embedding_pool.py` (EmbeddingResource, _parse_resource), `app/memory/simplified_embeddings.py` (_switch_backend)

---

## Gap 4: No Config Doctor Integration

**Problem:** LLM resource pool has `config doctor` checks. Embedding pool has no diagnostics.

**Fix:** Add `_check_embedding_pool()` to `ConfigDoctor` class. Check: each enabled resource's backend is importable, api_key resolves, server_url is reachable (for local/api backends).

**Files:** `app/config/doctor.py`

---

## Gap 5: Singleton Bypasses Config Changes

**Problem:** `get_embedding_pool()` caches forever. Config file changes require manual `reload()`.

**Fix:** Add `_config_mtime: float` to `EmbeddingPool`. On each `acquire()`, check if config file mtime changed → auto-reload. Cheap stat() call, no polling.

**Files:** `app/memory/embedding_pool.py` (acquire, _load_config)

---

## Gap 6: No HybridMemoryService Integration

**Problem:** `HybridMemoryService._setup_embedding()` creates its own `SimpleEmbedding` without going through the pool. Failover only works if you explicitly use the pool.

**Fix:** In `_setup_embedding()`, import `get_embedding_pool()` and create `SimpleEmbedding` with `preferred_model` from config. This wires the pool into the actual memory service.

**Files:** `submodules/dreaming-memory-pipeline/src/mojo_memory/services/memory_service.py` (or the shim in `app/memory/simplified_embeddings.py`)

---

## Gap 7: No MCP Tool for Pool Status

**Problem:** Users can't check embedding pool status or switch models at runtime via MCP.

**Fix:** Add `embedding_pool` action to the existing `config` MCP tool:
- `config(action="get", module="embedding_pool")` → list resources, status, priorities
- `config(action="set", module="embedding_pool", path="resources.<id>.priority", value=N)` → reprioritize

**Files:** `app/mcp/core/tools.py` (add embedding_pool module to config tool)

---

## Gap 8: Cache Invalidation on Failover

**Problem:** `SimpleEmbedding` cache is keyed by `model_name`. Failover to different backend = cache misses on both sides.

**Fix:** Change cache key from `model_name` to `{backend}:{model_name}:{embedding_dim}`. In `_init_cache()` and `_save_cache()`, use `self.model_version` (already computed) as cache key.

**Files:** `app/memory/simplified_embeddings.py` (_init_cache, _save_cache)

---

## Gap 9: No Migration CLI

**Problem:** `embedding_migration.py` exists but has no CLI or MCP integration. Users can't migrate between models.

**Fix:** Add CLI entry point: `python -m app.memory.embedding_migration --from bge-m3 --to text-embedding-3-small`. Add `embedding_migrate` action to config MCP tool.

**Files:** `app/memory/embedding_migration.py` (add `__main__` block), `app/mcp/core/tools.py`

---

## Gap 10: No Metrics/Logging

**Problem:** No tracking of which backend is used, failover counts, latency per backend.

**Fix:** Add `_stats: Dict[str, Dict]` to `EmbeddingPool` tracking `calls`, `failures`, `last_latency_ms` per resource_id. Log on each `acquire()` and `mark_failed()`. Expose via `list_resources()`.

**Files:** `app/memory/embedding_pool.py`

---

## Execution Order

1. Gap 3 (request_format fields) — unblocks Leon's OpenAI backend
2. Gap 1 (auto-recovery) — prevents permanent failures
3. Gap 2 (dimension mismatch) — prevents vector corruption
4. Gap 5 (auto-reload) — config changes take effect
5. Gap 8 (cache key) — prevents cache waste on failover
6. Gap 6 (HybridMemoryService) — wires pool into actual memory
7. Gap 10 (metrics) — observability
8. Gap 4 (config doctor) — diagnostics
9. Gap 7 (MCP tool) — user-facing status
10. Gap 9 (migration CLI) — user-facing migration

---

## Acceptance Criteria

1. Failover works: primary fails → next backend picked up → vectors stored with correct dimension
2. Auto-recovery: failed backend retried after 5 min
3. Config reload: change `~/.memory/config/embedding_pool.json` → pool picks up changes within 1 acquire() call
4. Dimension safety: no vector stored with wrong dimension after failover
5. MCP tool: `config(action="get", module="embedding_pool")` returns pool status
6. All existing tests pass + new tests for each gap
