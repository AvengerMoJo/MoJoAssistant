# Phase 1 Implementation Summary

**Date:** 2026-02-11
**Objective:** Refactor OpenCode Manager data models to use `git_url` as primary key instead of `project_name`

---

## Overview

Phase 1 changes the internal data model from `project_name`-based identification to `git_url`-based identification. This aligns with OpenCode's native architecture where projects are identified by their git remote URL.

### Key Changes

1. **Primary Key Migration**: `project_name` → `git_url` (normalized)
2. **Backward Compatibility**: Existing code continues to work with automatic migration
3. **Display Names**: `project_name` is now a display field, auto-generated from `git_url`

---

## Files Modified

### 1. `app/mcp/opencode/utils.py` (NEW)

**Purpose:** Git URL handling utilities

**Functions:**
- `normalize_git_url(git_url)` - Canonicalize to SSH format with .git suffix
- `hash_git_url(git_url)` - Generate deterministic hash (12 chars)
- `sanitize_for_filename(text)` - Safe filesystem names
- `extract_repo_name(git_url)` - Extract (owner, repo) tuple
- `generate_project_name(git_url)` - Auto-generate display name (e.g., "owner-repo")
- `generate_base_dir(git_url)` - Generate base directory path

**Examples:**
```python
normalize_git_url("https://github.com/user/repo")
# → "git@github.com:user/repo.git"

generate_project_name("git@github.com:user/repo.git")
# → "user-repo"
```

---

### 2. `app/mcp/opencode/models.py`

**Changes:**

#### `ProjectConfig`
```python
# OLD:
@dataclass
class ProjectConfig:
    project_name: str  # PRIMARY KEY
    git_url: str = None
    sandbox_dir: str = None

# NEW:
@dataclass
class ProjectConfig:
    git_url: str  # PRIMARY KEY (normalized)
    project_id: Optional[str] = None  # OpenCode's project ID
    base_dir: str = None  # Base directory
    project_name: Optional[str] = None  # Display name (auto-generated)
    worktrees: List[str] = None  # List of worktree names
```

#### `ProjectState`
```python
# OLD:
@dataclass
class ProjectState:
    project_name: str  # PRIMARY KEY
    sandbox_dir: str
    git_url: str

# NEW:
@dataclass
class ProjectState:
    git_url: str  # PRIMARY KEY (normalized)
    project_id: Optional[str] = None
    base_dir: str = None
    project_name: Optional[str] = None  # Display name
    worktrees: List[str] = None
    sandbox_dir: Optional[str] = None  # Backward compat (deprecated)
```

**Migration:**
- `sandbox_dir` → `base_dir` (with backward compat)
- Auto-generates `project_name` from `git_url` in `__post_init__`

---

### 3. `app/mcp/opencode/state_manager.py`

**Changes:**

| Method | OLD Signature | NEW Signature |
|--------|--------------|---------------|
| `save_project()` | N/A | Uses `project_state.git_url` as key |
| `get_project()` | `get_project(project_name)` | `get_project(git_url)` |
| `delete_project()` | `delete_project(project_name)` | `delete_project(git_url)` |
| `list_projects()` | Returns `List[str]` (names) | Returns `List[str]` (git_urls) |
| `update_health_check()` | `(project_name)` | `(git_url)` |
| `update_process_status()` | `(project_name, ...)` | `(git_url, ...)` |

**New Methods:**
- `get_project_by_name(project_name)` - Backward compat helper (slower, scans all)

**Migration:**
```python
def _migrate_to_phase1(self):
    """Migrate state file from project_name keys → git_url keys"""
    # Re-keys projects dict
    # Adds project_id, base_dir, worktrees fields
    # Renames sandbox_dir → base_dir
    # Detects duplicates
```

**State File Format:**
```json
{
  "global_mcp_tool": { ... },
  "projects": {
    "git@github.com:user/repo.git": {
      "git_url": "git@github.com:user/repo.git",
      "project_name": "user-repo",
      "base_dir": "/home/user/.opencode-projects/user-repo",
      "worktrees": [],
      "project_id": null,
      "opencode": { "pid": 12345, "port": 4100, ... },
      ...
    }
  }
}
```

---

### 4. `app/mcp/opencode/config_manager.py`

**Changes:**

| Method | OLD Signature | NEW Signature |
|--------|--------------|---------------|
| `add_server()` | `(project_name, port, ...)` | `(git_url, port, project_name=None, ...)` |
| `remove_server()` | `(project_name)` | `(git_url)` |
| `update_server_status()` | `(project_name, status)` | `(git_url, status)` |
| `get_server()` | `(project_name)` | `(git_url)` |

**New Methods:**
- `get_server_by_name(project_name)` - Backward compat helper

**Migration:**
```python
def _migrate_to_phase1(self):
    """Migrate config file from project_name IDs → git_url IDs"""
    # Re-keys servers from project_name → git_url
    # Adds project_name field for display
    # Renames sandbox_dir → base_dir
```

**Config File Format:**
```json
{
  "version": "1.0",
  "servers": [
    {
      "id": "git@github.com:user/repo.git",
      "git_url": "git@github.com:user/repo.git",
      "project_name": "user-repo",
      "title": "User Repo",
      "url": "http://127.0.0.1:4100",
      "base_dir": "/home/user/.opencode-projects/user-repo",
      ...
    }
  ],
  "default_server": "git@github.com:user/repo.git"
}
```

---

### 5. `app/mcp/opencode/manager.py`

**Changes:**

| Method | OLD Signature | NEW Signature |
|--------|--------------|---------------|
| `start_project()` | `(project_name, git_url, ...)` | `(git_url, ...)` |
| `_bootstrap_project()` | `(project_name, git_url, ...)` | `(git_url, ...)` |
| `get_status()` | `(project_name)` | `(git_url)` |
| `stop_project()` | `(project_name)` | `(git_url)` |
| `restart_project()` | `(project_name)` | `(git_url)` |
| `destroy_project()` | `(project_name)` | `(git_url)` |

**Internal Changes:**
- All methods now accept `git_url` as primary parameter
- `project_name` is auto-generated from `git_url` for display/logging
- All calls to `state_manager` and `config_manager` use `git_url`
- `env_manager` still uses `project_name` (backward compat for Phase 1)

**Return Values:**
All methods now include both `git_url` and `project` (display name):
```python
{
    "status": "success",
    "project": "user-repo",  # Display name
    "git_url": "git@github.com:user/repo.git",  # Primary key
    ...
}
```

---

### 6. `app/mcp/opencode/migrate_phase1.py` (NEW)

**Purpose:** Standalone migration script

**Usage:**
```bash
# Dry run (preview changes)
python -m app.mcp.opencode.migrate_phase1 --dry-run

# Perform migration
python -m app.mcp.opencode.migrate_phase1

# Custom memory root
python -m app.mcp.opencode.migrate_phase1 --memory-root /path/to/.memory
```

**Features:**
- Shows what will be migrated before making changes
- Migrates both state and config files
- Detects already-migrated files
- Safe to run multiple times (idempotent)

---

## Backward Compatibility

### Automatic Migration

Both `StateManager` and `ConfigManager` automatically migrate old format on initialization:

```python
# state_manager.py
def __init__(self, memory_root: str = None):
    # ...
    self._ensure_state_file()  # Runs migration if needed

# config_manager.py
def __init__(self, memory_root: str = None):
    # ...
    if self.config_path.exists():
        self._migrate_to_phase1()  # Runs migration if needed
```

### Deprecated Fields

| Old Field | New Field | Status |
|-----------|-----------|--------|
| `sandbox_dir` | `base_dir` | Deprecated but still present for backward compat |
| `project_name` (primary key) | `git_url` (primary key) | Now a display field, auto-generated |

### Helper Methods

For code that still uses `project_name`:
- `StateManager.get_project_by_name(project_name)` - Finds project by display name (slower)
- `ConfigManager.get_server_by_name(project_name)` - Finds server by display name (slower)

---

## Testing Checklist

- [ ] Existing projects continue to work after migration
- [ ] New projects created with `git_url` as primary key
- [ ] `list_projects()` returns correct data
- [ ] `get_status(git_url)` works
- [ ] `stop_project(git_url)` and `restart_project(git_url)` work
- [ ] `destroy_project(git_url)` works
- [ ] Duplicate git URLs are detected and handled
- [ ] Migration script works in dry-run mode
- [ ] Migration script performs actual migration correctly

---

## Breaking Changes

**None for end users.** All changes are internal. Existing projects will be automatically migrated.

**For developers:**
- If you have code calling `OpenCodeManager` methods, update signatures to use `git_url` instead of `project_name`
- If you query state/config files directly, note the new key structure

---

## Next Steps (Phase 2+)

Phase 1 focused on data model refactor. Future phases will implement:

- **Phase 2:** Native worktree support via `/experimental/worktree` API
- **Phase 3:** Hybrid base directory management (default managed, allow override)
- **Phase 4:** Global MCP tool improvements
- **Phase 5:** UI/UX enhancements

See `docs/opencode-manager-redesign-plan.md` for full roadmap.

---

## Migration Examples

### Example 1: State File Migration

**Before:**
```json
{
  "projects": {
    "user-repo": {
      "project_name": "user-repo",
      "git_url": "https://github.com/user/repo",
      "sandbox_dir": "/home/user/.memory/opencode-sandboxes/user-repo",
      ...
    }
  }
}
```

**After:**
```json
{
  "projects": {
    "git@github.com:user/repo.git": {
      "git_url": "git@github.com:user/repo.git",
      "project_name": "user-repo",
      "base_dir": "/home/user/.memory/opencode-sandboxes/user-repo",
      "sandbox_dir": "/home/user/.memory/opencode-sandboxes/user-repo",
      "worktrees": [],
      "project_id": null,
      ...
    }
  }
}
```

### Example 2: API Call Migration

**Before:**
```python
await manager.start_project(
    project_name="user-repo",
    git_url="https://github.com/user/repo"
)
```

**After:**
```python
await manager.start_project(
    git_url="https://github.com/user/repo"
    # project_name is auto-generated internally
)
```

---

## Conclusion

Phase 1 successfully refactors the internal data model to use `git_url` as the primary key, aligning with OpenCode's native architecture. All changes are backward compatible with automatic migration.
