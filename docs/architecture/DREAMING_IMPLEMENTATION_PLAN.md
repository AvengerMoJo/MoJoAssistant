# Dreaming Full Implementation Plan (A -> B -> C -> D)

## Goal
Complete Dreaming pipeline implementation so it is production-reliable, version-aware, and simple for users (system handles complexity automatically).

## Scope
- In scope:
  - A->B chunking reliability
  - B->C synthesis reliability
  - D versioning and lineage
  - Hot/cold behavior for latest vs historical archives
  - MCP tool consistency and tests
- Out of scope:
  - UI redesign
  - New external providers
  - Breaking changes to existing tool names

## Principles
1. Keep old data; do not delete historical archives by default.
2. Default retrieval should prioritize latest/hot data.
3. Users should not manage metadata manually.
4. Fail clearly when required config is invalid; fallback only when safe.

## Phase 1: A->B and B->C Reliability

### 1.1 Strict JSON output contract
- Update chunking/synthesis prompts to require JSON-only output.
- Add explicit schema examples in prompt payload.

### 1.2 Resilient parsing
- Implement parser strategy:
  1. Parse full response as JSON.
  2. If fails, extract first valid JSON object/array block and parse.
  3. If still fails, record parse error and use fallback path.
- Add structured error metadata for troubleshooting.

### 1.3 Fallback transparency
- Keep existing fallback chunking/synthesis.
- Mark fallback outputs with machine-readable metadata:
  - `used_fallback=true`
  - `fallback_reason`
  - `llm_provider`
  - `model`

## Phase 2: D Versioning (Real, Incremental)

### 2.1 Version increment logic
- For each `conversation_id`, detect latest archive file `archive_vN.json`.
- New archive version = `N + 1` (or `1` if none exists).
- Remove hardcoded `version: 1` behavior.

### 2.2 Save and retrieval semantics
- Continue storing as `archive_v{version}.json`.
- `get_archive(version=None)` returns latest.
- `get_archive(version=N)` returns exact version or `None`.

### 2.3 Archive listing accuracy
- `list_archives()` must show:
  - `latest_version`
  - `quality_level` of latest
  - timestamps
  - counts

## Phase 3: Superseded Lineage + Hot/Cold

### 3.1 Lineage metadata
- Add lineage fields to archive metadata:
  - `previous_version`
  - `supersedes_version`
  - `is_latest`
  - `status` (`active` or `superseded`)

### 3.2 Hot/cold policy
- New latest version:
  - `is_latest=true`
  - `storage_location=hot`
  - `status=active`
- Older versions:
  - `is_latest=false`
  - `storage_location=cold`
  - `status=superseded`

### 3.3 Non-destructive archive model
- Never auto-delete old versions.
- Keep full snapshots for audit/reference.

## Phase 4: MCP Tool Behavior Alignment

### 4.1 `dreaming_process`
- Return created version and whether previous version was superseded.

### 4.2 `dreaming_get_archive`
- Keep current signature.
- Ensure latest semantics are deterministic.

### 4.3 `dreaming_list_archives`
- Return latest status summary and lineage hints.

### 4.4 `dreaming_upgrade_quality`
- Upgrade should create a new version, not overwrite prior.
- Preserve `upgraded_from` and `upgraded_to`.

## Phase 5: Tests and Acceptance

### 5.1 Unit tests
- JSON parsing fallback behavior.
- Version increment logic.
- Lineage metadata assignment.

### 5.2 Integration tests
- Repeated `dreaming_process` on same `conversation_id` creates v1, v2, v3...
- `get_archive(None)` returns highest version.
- `get_archive(version=N)` returns exact version.
- `upgrade_quality` creates next version and preserves previous versions.

### 5.3 Real-memory validation
- Run off-schedule dreaming on real memory slice.
- Verify:
  - archive created
  - version increments
  - latest marked hot/active
  - older versions cold/superseded

## Execution Order
1. Phase 1 (reliability)
2. Phase 2 (versioning)
3. Phase 3 (lineage + hot/cold)
4. Phase 4 (tool alignment)
5. Phase 5 (tests + validation)

## Definition of Done
1. A->B->C->D runs with deterministic JSON handling.
2. Versioning is incremental and queryable.
3. Historical versions remain preserved.
4. Latest/hot behavior is automatic and default.
5. MCP tools and tests reflect final behavior.
