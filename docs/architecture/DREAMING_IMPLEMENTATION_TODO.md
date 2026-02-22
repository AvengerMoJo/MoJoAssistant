# Dreaming Implementation TODO

Branch: `wip_dreaming_full_implementation`

## Phase 1: Reliability (A->B, B->C)
- [x] Enforce strict JSON-only response instructions in chunker prompt.
- [x] Enforce strict JSON-only response instructions in synthesizer prompt.
- [x] Implement resilient JSON extraction parser in chunker.
- [x] Implement resilient JSON extraction parser in synthesizer.
- [x] Replace rule-based fallback output with fail-fast behavior.
- [x] Add one LLM JSON-repair retry before failing the run.
- [x] Ensure failures are explicit with provider/model/error details for debugging.
- [ ] Add/adjust tests for parser and fallback behavior.

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
- [ ] `dreaming_process`: include created version and superseded info in response.
- [ ] `dreaming_list_archives`: expose latest status and version fields.
- [ ] `dreaming_upgrade_quality`: create new version (do not overwrite old).
- [ ] Maintain backwards compatibility of tool signatures.

## Phase 5: Validation
- [ ] Unit tests for version increment and lineage transitions.
- [ ] Integration test for repeated process on same `conversation_id` (v1, v2, v3).
- [ ] Integration test for upgrade-quality producing next version.
- [ ] Real-memory off-schedule validation with LM Studio configured.
- [ ] Confirm default retrieval favors hot/latest while history remains available.
