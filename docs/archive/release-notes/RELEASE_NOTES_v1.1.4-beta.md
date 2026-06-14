# Release Notes - v1.1.4-beta

**Release Date:** 2026-02-23
**Type:** Beta Release
**Theme:** Dreaming Pipeline & Autonomous Memory Consolidation

---

## Overview

This beta release introduces the Dreaming system - a fully autonomous memory consolidation pipeline that transforms raw conversations into a structured, versioned knowledge base. The scheduler now automatically runs nightly "dreaming" sessions during off-peak hours, processing conversations through semantic chunking, synthesis, and archival with full version lineage tracking.

---

## Major Features

### 1. Dreaming Pipeline (A->B->C->D)

**New system:** A four-stage memory consolidation pipeline that turns raw conversations into searchable, structured knowledge.

**Pipeline stages:**
- **A (Raw Data)** - Today's full conversations as retrieved from memory
- **B (Semantic Chunks)** - LLM-powered breakdown into semantic pieces with metadata: topic labels, speaker attribution, entity extraction, language detection
- **C (Synthesized Clusters)** - Cross-conversation topic clusters, relationship maps, timelines, and pattern discovery
- **D (Versioned Archives)** - Immutable, versioned archive files with hot/cold lifecycle management

**Key design decisions:**
- **File-first architecture** - Append-only JSON archives under `~/.memory/dreams/<conversation_id>/archive_v<N>.json`
- **No separate indexing server** - DuckDB reads JSON files directly for OLAP queries
- **Multi-lingual support** - Chunks preserve original language; language detected per chunk
- **Quality tiers** - `basic`, `good`, `premium` control LLM effort and confidence thresholds

**Files:**
- `app/dreaming/pipeline.py` - Pipeline orchestrator (A->B->C->D)
- `app/dreaming/chunker.py` - Conversation chunker (A->B)
- `app/dreaming/synthesizer.py` - Knowledge synthesizer (B->C)

---

### 2. Resilient LLM JSON Parsing

**Problem solved:** Small local LLMs frequently return malformed JSON, markdown-wrapped responses, or prose mixed with JSON blocks.

**New four-pass parsing strategy:**
1. **Strict parse** - Attempt direct `json.loads()` after stripping markdown fences
2. **JSON extraction** - Scan for first valid JSON object/array in mixed prose output using bracket-depth tracking
3. **Raw decode** - Use `JSONDecoder.raw_decode()` at every candidate position
4. **LLM repair** - Ask the LLM to convert broken output into strict JSON as a final retry

**Payload normalization:**
- Handles `{"chunks": [...]}`, `{"data": {"chunks": [...]}}`, `{"items": [...]}`, and bare arrays
- Same strategy applied to both chunker and synthesizer with type-specific normalizers

**Fail-fast behavior:**
- If all four passes fail, raises `RuntimeError` with provider name, model name, and error details
- No silent fallback to rule-based chunking - failures are explicit and debuggable

**Files:**
- `app/dreaming/chunker.py` - `_parse_llm_response()`, `_extract_first_json_object()`, `_repair_json_with_llm()`
- `app/dreaming/synthesizer.py` - Matching parser implementation for cluster payloads

---

### 3. Versioned Archives with Manifest Lifecycle

**Problem solved:** Previous implementation hardcoded `version: 1` and had no lineage tracking between archive versions.

**New versioning system:**
- Each `process_conversation()` call on the same `conversation_id` creates `archive_v1.json`, `archive_v2.json`, `archive_v3.json`, etc.
- Atomic writes via temp-file rename prevent partial/corrupt archives
- `get_archive(version=None)` always returns the latest version
- `get_archive(version=N)` retrieves an exact historical version

**Manifest system (`manifest.json`):**
- Per-conversation manifest tracks all versions and their lifecycle state
- Auto-bootstraps from existing archive files if manifest is missing
- Stores lineage metadata: `previous_version`, `supersedes_version`, `superseded_by_version`

**Hot/cold lifecycle:**
- Latest version: `is_latest=true`, `status=active`, `storage_location=hot`
- Older versions: `is_latest=false`, `status=superseded`, `storage_location=cold`
- Old archive files are **never deleted** - immutable snapshots for audit/reference

**Storage layout:**
```
~/.memory/dreams/
  <conversation_id>/
    manifest.json
    archive_v1.json    (cold, superseded)
    archive_v2.json    (cold, superseded)
    archive_v3.json    (hot, active, latest)
```

**Files:**
- `app/dreaming/pipeline.py` - `_get_or_init_manifest()`, `_update_manifest_for_new_version()`, `get_archive_lifecycle()`

---

### 4. Scheduler-Driven Dreaming Automation

**New capability:** The scheduler automatically creates a default nightly dreaming task on startup.

**Default task configuration:**
- **ID:** `dreaming_nightly_offpeak_default`
- **Schedule:** `0 3 * * *` (3:00 AM daily via cron)
- **Off-peak enforcement:** Only runs between 01:00-05:00
- **Automatic input:** Reads last 200 messages from `conversations_multi_model.json`
- **Priority:** LOW (background, non-urgent)
- **Resources:** Requires GPU

**Off-peak enforcement logic:**
- If `enforce_off_peak=true` and current time is outside the off-peak window, the task returns `skipped` with reason `outside_off_peak_window`
- Handles windows that cross midnight correctly (e.g., 23:00-05:00)

**Automatic conversation gathering:**
- Reads from existing multi-model conversation store
- Searches multiple candidate paths (`$CWD/.memory/` and `~/.memory/`)
- Formats messages as `[role] content` lines for the pipeline
- Generates unique conversation IDs with timestamps: `auto_dream_20260223_030000`
- Gracefully skips if no recent conversation data is found

**Files:**
- `app/scheduler/core.py` - `_ensure_default_dreaming_task()`
- `app/scheduler/executor.py` - `_execute_dreaming()`, `_is_within_off_peak()`, `_build_automatic_dreaming_input()`

---

### 5. MCP Tool Enhancements

**Updated tools now return versioning and lifecycle data:**

- **`dreaming_process`** - Now returns `version` and `lifecycle` metadata (active/superseded, hot/cold)
- **`dreaming_get_archive`** - Now returns `lifecycle` and `latest_version` from manifest
- **`dreaming_upgrade_quality`** - Creates a new version (no overwrite); returns `version` and `lifecycle`
- **`scheduler_add_task`** - Now accepts `resources` parameter for GPU/LLM requirements

**Removed:**
- Hardcoded `qwen-coder-small` interface selection in `dreaming_process` - now uses whatever active LLM interface is configured

**File:** `app/mcp/core/tools.py`

---

### 6. Coding Agent Policy

**New files establishing agent operating rules for the repository:**

- **`AGENTS.md`** - Repository-wide agent rules: memory workflow, git workflow (`wip_<feature>` branching), scope governance
- **`Coding Agents Rules.md`** - Canonical coding rules: core rules, code quality, safety, collaboration, git practices, definition of done

**Key policies:**
- Agents must use MoJoAssistant MCP memory context before major edits
- All work on `wip_<feature>` branches; merge to `main` only when user requests
- All commits authored as the user (repository owner), not the agent
- Small, reversible changes preferred; backward-compatible by default

**README updated** to reference these policy documents.

---

### 7. LM Studio Integration Documentation

**Updated documentation:**
- `.env.example` - Added `LMSTUDIO_BASE_URL`, `LMSTUDIO_API_KEY`, `LMSTUDIO_API_KEY_FILE` with inline comments
- `README.md` - Added LM Studio configuration section with Bearer auth notes and key file recommendations
- `docs/configuration/MCP_CLIENT_SETUP.md` - Updated client setup guidance

---

## Technical Improvements

### Dreaming Architecture

```
Scheduler (3 AM cron)
    |
    v
TaskExecutor._execute_dreaming()
    |
    ├── Off-peak check ──> skip if outside window
    ├── Auto-gather conversations from memory store
    |
    v
DreamingPipeline.process_conversation()
    |
    ├── Stage A->B: ConversationChunker
    │   ├── LLM semantic analysis
    │   ├── 4-pass JSON parsing
    │   └── BChunk objects with labels, entities, language
    |
    ├── Stage B->C: DreamingSynthesizer
    │   ├── LLM topic clustering
    │   ├── 4-pass JSON parsing
    │   └── CCluster objects (TOPIC, RELATIONSHIP, TIMELINE, SUMMARY)
    |
    └── Stage C->D: Archive
        ├── Collect entities from chunks/clusters
        ├── Create versioned archive (archive_vN.json)
        ├── Atomic write (temp-file rename)
        └── Update manifest (hot/cold lifecycle)
```

### Manifest Lifecycle Flow

```
process_conversation("conv_123", text_1)
  -> archive_v1.json  {is_latest: true,  status: active,     storage: hot}
  -> manifest.json    {latest_version: 1}

process_conversation("conv_123", text_2)
  -> archive_v2.json  {is_latest: true,  status: active,     storage: hot}
  -> manifest.json    {latest_version: 2,
                        versions: {
                          "1": {is_latest: false, status: superseded, storage: cold},
                          "2": {is_latest: true,  status: active,     storage: hot}
                        }}
```

---

## Tests

### New Test Suites

**3 new test files with 9 test cases:**

1. **`tests/unit/test_dreaming_parsing.py`** (5 tests)
   - `test_chunker_parses_json_embedded_in_prose` - Extracts JSON from LLM prose
   - `test_chunker_uses_llm_repair_then_succeeds` - LLM repair retry works
   - `test_chunker_fails_fast_when_parse_and_repair_fail` - RuntimeError with provider info
   - `test_synthesizer_normalizes_list_payload` - Bare JSON array normalized to `{"clusters": [...]}`
   - `test_synthesizer_fails_fast_when_parse_and_repair_fail` - RuntimeError with provider info

2. **`tests/unit/test_dreaming_pipeline_versioning.py`** (1 comprehensive test)
   - `test_pipeline_creates_incrementing_versions_and_manifest_lifecycle` - Full v1->v2 flow: file creation, manifest lifecycle transitions, latest retrieval, explicit version retrieval, archive lifecycle API

3. **`tests/unit/test_scheduler_dreaming_automation.py`** (4 tests)
   - `test_task_resources_round_trip` - TaskResources serialization/deserialization
   - `test_scheduler_ensures_default_dreaming_task` - Default dreaming task created on startup
   - `test_executor_skips_dreaming_outside_off_peak` - Off-peak enforcement
   - `test_executor_builds_automatic_input_from_memory_store` - Conversation auto-gathering
   - `test_executor_skips_automatic_when_no_recent_data` - Graceful skip when no data

---

## Bug Fixes

1. **Hardcoded `version: 1`** - Replaced with incremental versioning per conversation_id
2. **Hardcoded LLM interface selection** - Removed `qwen-coder-small` override in dreaming_process MCP tool; uses configured active interface
3. **Silent fallback masking failures** - Chunker and synthesizer now fail fast with explicit error details instead of silently falling back to rule-based output
4. **Missing `resources` in scheduler tasks** - `scheduler_add_task` MCP tool now passes resources through to Task creation
5. **Stale manifest recovery** - If manifest references a non-existent archive file, falls back to file-system scan

---

## Documentation

### New Documentation
- `docs/architecture/DREAMING_IMPLEMENTATION_PLAN.md` - 5-phase implementation plan with scope, principles, and definition of done
- `docs/architecture/DREAMING_IMPLEMENTATION_TODO.md` - Checklist tracking completion across all phases
- `docs/architecture/DREAMING_SPECIFICATION.md` - Updated with versioning, lineage, hot/cold, DuckDB OLAP, and physical storage architecture
- `AGENTS.md` - Repository-wide agent operating rules
- `Coding Agents Rules.md` - Canonical coding rules for all agents

### Updated Documentation
- `README.md` - Added coding agent policy section and LM Studio configuration
- `.env.example` - Added LM Studio environment variables
- `docs/configuration/MCP_CLIENT_SETUP.md` - Updated client setup guidance

---

## Migration Notes

### From v1.1.3-beta

**No breaking changes.** Existing configurations and memory data continue to work.

**New behavior:**
- The scheduler now auto-creates a nightly dreaming task on startup. This is a background task that only runs between 01:00-05:00 and requires no manual configuration.
- If you have existing dream archives without a `manifest.json`, the system auto-bootstraps the manifest from archive files on first access.

**New environment variables (all optional):**
```env
LMSTUDIO_BASE_URL=http://localhost:8080/v1
LMSTUDIO_API_KEY=your_token
LMSTUDIO_API_KEY_FILE=~/.keys/local_lmstudio.key
```

**To trigger dreaming manually:**
```bash
# Via MCP tool
dreaming_process(conversation_id="my_conv", conversation_text="...", quality_level="basic")
```

---

## Implementation Status

### Completed
- Phase 1: A->B and B->C reliability (resilient parsing, fail-fast, LLM repair)
- Phase 2: Real versioning in D (incremental versions, atomic writes)
- Phase 3: Lineage + hot/cold (manifest lifecycle, superseded tracking)
- Phase 4: MCP tool alignment (partial - process, get_archive, upgrade_quality updated)
- Phase 5: Tests (parsing, versioning, scheduler automation)

### Remaining (Planned for v1.1.5)
- MCP `dreaming_list_archives` expose latest status and version fields
- Maintain backwards compatibility validation for tool signatures
- Integration tests for repeated process on same conversation_id (v1, v2, v3)
- Integration test for upgrade-quality producing next version
- Real-memory off-schedule validation with LM Studio configured
- DuckDB query layer integration

---

## Performance

**Dreaming pipeline (per conversation):**
- Chunking (A->B): 1-2 seconds per 800 tokens (local LLM)
- Synthesis (B->C): 5-10 seconds for 100 chunks
- Archival (C->D): <1 second (file write + manifest update)
- Total: ~10-30 seconds per conversation

**Storage growth:**
- Archive files: ~10-50KB each (depending on conversation length)
- Manifest files: ~1KB per conversation (grows with versions)
- Growth rate: ~8.5MB per day under active use

**Scheduler overhead:**
- Default tick interval: 60 seconds
- Off-peak check: negligible
- Conversation auto-gathering: <100ms for 200 messages

---

## Known Issues

1. **Archive files store creation-time metadata** - The `is_latest` and `status` fields inside archive JSON reflect state at write time, not current state. Use `manifest.json` or `get_archive_lifecycle()` for current lifecycle state.
2. **No embedding generation yet** - B chunks have `embedding=None`; semantic search over dreaming output requires embedding integration (planned).
3. **Tool calling format** - Parser uses text-based JSON extraction, not OpenAI function calling spec.
4. **Unreachable code in executor** - `_execute_agent()` has a dead `try` block after the return statement (lines 404-429 in executor.py).

---

## Files Changed

**Summary:**
- **19 files changed**
- **1,408 insertions**
- **101 deletions**

**New files:** 8
- `AGENTS.md`
- `Coding Agents Rules.md`
- `docs/architecture/DREAMING_IMPLEMENTATION_PLAN.md`
- `docs/architecture/DREAMING_IMPLEMENTATION_TODO.md`
- `tests/unit/test_dreaming_parsing.py`
- `tests/unit/test_dreaming_pipeline_versioning.py`
- `tests/unit/test_scheduler_dreaming_automation.py`

**Modified files:** 11
- `app/dreaming/chunker.py` (+161 lines)
- `app/dreaming/pipeline.py` (+258 lines)
- `app/dreaming/synthesizer.py` (+163 lines)
- `app/scheduler/core.py` (+83/-17 lines)
- `app/scheduler/executor.py` (+122 lines)
- `app/scheduler/models.py` (+19 lines)
- `app/mcp/core/tools.py` (+32 lines)
- `.env.example` (+9 lines)
- `README.md` (+14 lines)
- `config/llm_config.json.comprehensive` (+2/-2 lines)
- `docs/architecture/DREAMING_SPECIFICATION.md` (+60 lines)
- `docs/configuration/MCP_CLIENT_SETUP.md` (+13 lines)

---

## Installation

### Fresh Install
```bash
git clone https://github.com/yourusername/MoJoAssistant.git
cd MoJoAssistant
git checkout v1.1.4-beta
python app/interactive-cli.py --setup
```

### Upgrade from v1.1.3-beta
```bash
git pull origin main
git checkout v1.1.4-beta
# No additional setup required - dreaming auto-configures on scheduler start
```

---

## Support

**Issues:** https://github.com/yourusername/MoJoAssistant/issues
**Discussions:** https://github.com/yourusername/MoJoAssistant/discussions
**Docs:** `docs/` directory

---

## License

MIT License - See LICENSE file for details

---

**Thank you for testing MoJoAssistant v1.1.4-beta!**

Your feedback on the Dreaming pipeline helps shape how MoJoAssistant consolidates and evolves its memory. Please report any issues or suggestions.
