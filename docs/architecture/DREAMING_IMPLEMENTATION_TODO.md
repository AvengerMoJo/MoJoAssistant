# Dreaming Implementation TODO

Branch: merged to `main` as of v1.1.4-beta

## Phase 1: Reliability (A->B, B->C)
- [x] Enforce strict JSON-only response instructions in chunker prompt.
- [x] Enforce strict JSON-only response instructions in synthesizer prompt.
- [x] Implement resilient JSON extraction parser in chunker.
- [x] Implement resilient JSON extraction parser in synthesizer.
- [x] Replace rule-based fallback output with fail-fast behavior.
- [x] Add one LLM JSON-repair retry before failing the run.
- [x] Ensure failures are explicit with provider/model/error details for debugging.
- [x] Add/adjust tests for parser and fallback behavior (9 test cases in v1.1.4-beta).

## Phase 2: Real Versioning in D
- [x] Implement `latest_version + 1` logic per `conversation_id`.
- [x] Remove hardcoded `version = 1`.
- [x] Ensure `archive_vN.json` is written with atomic temp-file rename.
- [x] Validate `get_archive(version=None)` returns latest consistently.
- [x] Validate `get_archive(version=N)` exact retrieval.

## Phase 3: Lineage + Hot/Cold
- [x] Add lineage metadata (`previous_version`, `supersedes_version`).
- [x] Add lifecycle metadata (`is_latest`, `status`, `storage_location`).
- [x] Mark previous latest as `superseded/cold` when creating new version.
- [x] Keep all historical versions immutable and queryable.

## Phase 4: MCP Tool Alignment
- [x] `dreaming_process`: include created version and superseded info in response.
- [x] `dreaming_list_archives`: expose latest status and version fields.
- [x] `dreaming_upgrade_quality`: create new version (do not overwrite old).
- [x] Maintain backwards compatibility of tool signatures.
- [x] Fix: store `original_text` in metadata during `dreaming_process` so `upgrade_quality` can re-process.

## Phase 5: Validation
- [x] Unit tests for version increment and lineage transitions.
- [x] Integration test for repeated process on same `conversation_id` (v1, v2, v3).
- [x] Integration test for upgrade-quality producing next version.
- [ ] Real-memory off-schedule validation with LM Studio configured.
- [x] Confirm default retrieval favors hot/latest while history remains available.
