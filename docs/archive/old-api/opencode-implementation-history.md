# OpenCode Manager Implementation History

> **Note (2026-02):** The `opencode_*` and `claude_code_*` tool names referenced in this document have been replaced by unified `agent_*` tools (`agent_start`, `agent_stop`, `agent_status`, `agent_list`, `agent_restart`, `agent_destroy`, `agent_action`, `agent_list_types`). This document is preserved for historical reference.

This document consolidates the implementation phases of the OpenCode Manager redesign (git_url-based architecture). For the current API specification, see `opencode-api-spec.md`. For the overall redesign plan, see `opencode-manager-redesign-plan.md`.

---

## Phase 1: Core Architecture (2026-02-11) — Complete

**Objective:** Refactor data models to use `git_url` as primary key instead of `project_name`.

### Key Changes
- **Primary Key Migration**: `project_name` → `git_url` (normalized SSH format)
- **Auto-generated Display Names**: `project_name` derived from `git_url` (e.g., `owner-repo`)
- **Backward Compatibility**: Automatic migration in StateManager and ConfigManager
- **New Utilities** (`utils.py`): `normalize_git_url()`, `hash_git_url()`, `generate_project_name()`, etc.

### Files Modified
- `app/mcp/opencode/utils.py` (new)
- `app/mcp/opencode/models.py` — `ProjectConfig` and `ProjectState` updated
- `app/mcp/opencode/state_manager.py` — all methods accept `git_url`
- `app/mcp/opencode/config_manager.py` — all methods accept `git_url`
- `app/mcp/opencode/manager.py` — all methods accept `git_url`
- `app/mcp/opencode/migrate_phase1.py` (new) — standalone migration script

### Migration
Automatic on initialization. Standalone: `python -m app.mcp.opencode.migrate_phase1 [--dry-run]`

---

## Phase 2: Worktree/Sandbox Management — Complete

**Objective:** Add git worktree support for isolated development environments within a single project.

- WorktreeManager wraps `/experimental/worktree` API
- Integrated with OpenCodeManager
- Sandbox create, list, delete, and reset operations

---

## Phase 3: MCP Tools Update (2026-02-11) — Complete

**Objective:** Update MCP tool definitions to use git_url-based architecture and expose worktree functionality.

### Tool Renames
| Old Name | New Name |
|----------|----------|
| `opencode_start` | `opencode_project_start` |
| `opencode_status` | `opencode_project_status` |
| `opencode_stop` | `opencode_project_stop` |
| `opencode_restart` | `opencode_project_restart` |
| `opencode_destroy` | `opencode_project_destroy` |
| `opencode_list` | `opencode_project_list` |

### New Sandbox Tools
- `opencode_sandbox_create(git_url, name, branch, start_command)`
- `opencode_sandbox_list(git_url)`
- `opencode_sandbox_delete(git_url, name)`
- `opencode_sandbox_reset(git_url, name)`

### Breaking Changes
- `project_name` parameter removed from all tools (auto-generated from `git_url`)
- Response format includes both `git_url` (primary key) and `project` (display name)

---

## Phase 4: SSH Deploy Key Management — Complete

- `opencode_get_deploy_key` tool added
- Auto-generation of SSH keys per `git_url`

---

## Phase 5: Migration & Testing Plan — In Progress

**Objective:** Validate complete system, handle edge cases, ensure production readiness.

### Remaining Work
- Comprehensive unit and integration tests (>80% coverage target)
- Duplicate project detection across different base directories
- Port conflict auto-resolution (range 4100-4199)
- Orphaned process cleanup on manager startup
- User documentation and troubleshooting guides
- Structured logging and user-friendly error messages

---

## Current Status

As of v1.1.4-beta, OpenCode Manager is an **optional component** (disabled by default). Enable with `ENABLE_OPENCODE=true` in `.env`.

The git_url-based architecture (Phases 1-4) is implemented. Phase 5 testing and polish is ongoing.
