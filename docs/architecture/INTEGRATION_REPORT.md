# Scheduler and Dreaming Integration Report

## Summary
The Scheduler and Dreaming features have been successfully integrated into the MoJoAssistant core system. This enables automated memory consolidation (Dreaming) and persistent task scheduling.

## Changes Implemented

### 1. BChunk Serialization Fix
**File:** `app/dreaming/models.py`
- Added optional quality tracking fields (`quality_level`, `needs_upgrade`, `llm_used`, `language`) to the `BChunk` dataclass.
- **Why:** To ensure these fields (populated by `chunker.py`) are preserved when saving B chunks to JSON. Previously, `asdict()` would discard them as they were dynamically added attributes.

### 2. MemoryService Integration
**File:** `app/services/memory_service.py`
- **Scheduler Initialization:** The `Scheduler` is now initialized within `MemoryService`.
- **Background Execution:** Added `start_scheduler()` to run the scheduler loop in a daemon thread.
- **Dreaming Trigger:** Added `trigger_dreaming(conversation_id=None)` method.
    - Scans `archival_memory` for conversations.
    - Creates `TaskType.DREAMING` tasks for each conversation.
    - Submits tasks to the scheduler.
    - Prevents duplicate tasks for the same conversation.

### 3. CLI Enhancements
**File:** `app/interactive-cli.py`
- **Startup Flag:** Added `--scheduler` argument (default: `true`).
- **Commands:**
    - `/dream [conversation_id]`: Triggers the dreaming process. If no ID provided, scans all conversations.
    - `/scheduler`: Displays current scheduler status, running task, and queue statistics.

## How to Use

### Starting the App
The scheduler starts automatically by default:
```bash
python app/interactive-cli.py
```
To disable it:
```bash
python app/interactive-cli.py --scheduler false
```

### Triggering Dreaming
Inside the CLI:
1. **Run Dreaming:**
   ```
   > /dream
   ✅ Triggered 5 dreaming tasks
   ```
2. **Check Status:**
   ```
   > /scheduler
   ===== SCHEDULER STATUS =====
   Running: True
   Tick Count: 42
   Current Task: dreaming_conv_123 (dreaming)
   Queue: 4 tasks
     - pending: 4
   ==========================
   ```

### Verifying Results
Dreaming artifacts (B chunks, C clusters, D archives) will be stored in:
`~/.memory/dreams/`

## Next Steps
- **Automated Triggering:** Currently, dreaming must be triggered manually via `/dream` or by code. Future updates should add a "scan on startup" or "end of day" trigger in `MemoryService`.
- **Smart Filtering:** The current implementation scans *all* conversations in archival memory. Performance optimization is needed to only scan new/modified conversations.
- **Integration Tests:** Add end-to-end tests verifying that a conversation added to memory eventually results in a D archive.
