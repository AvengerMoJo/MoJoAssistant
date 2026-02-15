# Phase 3: MCP Tools Update Plan

**Date:** 2026-02-11
**Objective:** Update MCP tool definitions to use git_url-based architecture and expose Phase 2 worktree functionality

---

## Current Tools (project_name-based)

### Project Lifecycle Tools
1. `opencode_start(project_name, git_url, user_ssh_key)` - Start project
2. `opencode_status(project_name)` - Get project status
3. `opencode_stop(project_name)` - Stop project
4. `opencode_restart(project_name)` - Restart project
5. `opencode_destroy(project_name)` - Destroy project
6. `opencode_list()` - List all projects

### Global MCP Tool Management
7. `opencode_mcp_status()` - Get global MCP tool status
8. `opencode_mcp_restart()` - Restart global MCP tool
9. `opencode_stop_mcp_tool()` - Stop global MCP tool

### LLM Configuration
10. `opencode_llm_config()` - Get LLM configuration
11. `opencode_llm_set_model(model)` - Set default LLM model

---

## New Tools (git_url-based + worktrees)

### Project Lifecycle Tools (Updated)
1. **`opencode_project_start(git_url, user_ssh_key)`**
   - **Change:** Remove `project_name` parameter (auto-generated from git_url)
   - **Returns:** `{status, project, git_url, opencode_port, mcp_tool_port, base_dir, message}`

2. **`opencode_project_status(git_url)`**
   - **Change:** Use git_url instead of project_name
   - **Returns:** `{status, project, git_url, opencode: {...}, global_mcp_tool: {...}, base_dir}`

3. **`opencode_project_stop(git_url)`**
   - **Change:** Use git_url instead of project_name
   - **Returns:** `{status, project, git_url, message}`

4. **`opencode_project_restart(git_url)`**
   - **Change:** Use git_url instead of project_name
   - **Returns:** `{status, project, git_url, opencode_port, mcp_tool_port, message}`

5. **`opencode_project_destroy(git_url)`**
   - **Change:** Use git_url instead of project_name
   - **Returns:** `{status, project, git_url, message}`

6. **`opencode_project_list()`**
   - **Change:** Return format includes git_url
   - **Returns:** `{status, projects: [{git_url, name, opencode_running, opencode_port, base_dir}]}`

### Sandbox/Worktree Management (NEW - Phase 2)
7. **`opencode_sandbox_create(git_url, name, branch, start_command)`**
   - **Description:** Create a git worktree (sandbox) for isolated development
   - **Parameters:**
     - `git_url` (required): Git repository URL
     - `name` (required): Worktree name (unique within project)
     - `branch` (optional): Branch to checkout (default: current branch)
     - `start_command` (optional): Command to run on creation
   - **Returns:** `{status, project, git_url, worktree: {name, branch, directory}, message}`

8. **`opencode_sandbox_list(git_url)`**
   - **Description:** List all worktrees (sandboxes) for a project
   - **Parameters:**
     - `git_url` (required): Git repository URL
   - **Returns:** `{status, project, git_url, worktrees: [paths...], count}`

9. **`opencode_sandbox_delete(git_url, name)`**
   - **Description:** Delete a worktree (sandbox)
   - **Parameters:**
     - `git_url` (required): Git repository URL
     - `name` (required): Worktree name to delete
   - **Returns:** `{status, project, git_url, message}`

10. **`opencode_sandbox_reset(git_url, name)`**
    - **Description:** Reset worktree to clean state (default branch)
    - **Parameters:**
      - `git_url` (required): Git repository URL
      - `name` (required): Worktree name to reset
    - **Returns:** `{status, project, git_url, message}`

### Global MCP Tool Management (Unchanged)
11. `opencode_mcp_status()` - No changes
12. `opencode_mcp_restart()` - No changes
13. `opencode_stop_mcp_tool()` - No changes

### LLM Configuration (Unchanged)
14. `opencode_llm_config()` - No changes
15. `opencode_llm_set_model(model)` - No changes

---

## Implementation Changes

### Tool Definitions (_define_tools method)

**Remove:**
```python
{
    "name": "opencode_start",
    "inputSchema": {
        "properties": {
            "project_name": {...},
            "git_url": {...},
            ...
        },
        "required": ["project_name", "git_url"]
    }
}
```

**Add:**
```python
{
    "name": "opencode_project_start",
    "description": "Start an OpenCode project. The project name is auto-generated from the git URL. Creates base directory at ~/.opencode-projects/{owner}-{repo} by default.",
    "inputSchema": {
        "properties": {
            "git_url": {
                "type": "string",
                "description": "Git repository URL (SSH or HTTPS format, will be normalized)"
            },
            "user_ssh_key": {
                "type": "string",
                "description": "Optional: Path to user's SSH key"
            }
        },
        "required": ["git_url"]
    }
},
{
    "name": "opencode_sandbox_create",
    "description": "Create a git worktree (sandbox) for isolated development. Worktrees share the same .git database but have separate working directories and can be on different branches.",
    "inputSchema": {
        "properties": {
            "git_url": {
                "type": "string",
                "description": "Git repository URL"
            },
            "name": {
                "type": "string",
                "description": "Worktree name (unique within project)",
                "pattern": "^[a-zA-Z0-9_-]+$"
            },
            "branch": {
                "type": "string",
                "description": "Optional: Branch to checkout (default: current branch)"
            },
            "start_command": {
                "type": "string",
                "description": "Optional: Command to run after creation"
            }
        },
        "required": ["git_url", "name"]
    }
}
```

### Execution Methods

**Update:**
```python
async def _execute_opencode_start(self, args: Dict[str, Any]) -> Dict[str, Any]:
    # OLD
    project_name = args.get("project_name")
    git_url = args.get("git_url")
    result = await self.opencode_manager.start_project(project_name, git_url, ...)

    # NEW
    git_url = args.get("git_url")
    result = await self.opencode_manager.start_project(git_url, ...)
```

**Add:**
```python
async def _execute_opencode_sandbox_create(self, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute opencode_sandbox_create tool"""
    git_url = args.get("git_url")
    name = args.get("name")
    branch = args.get("branch")
    start_command = args.get("start_command")

    try:
        result = await self.opencode_manager.create_sandbox(
            git_url, name, branch, start_command
        )
        return result
    except Exception as e:
        return {"status": "error", "message": f"Failed to create sandbox: {str(e)}"}
```

### Routing Updates (execute method)

**Update:**
```python
# OLD
elif name == "opencode_start":
    return await self._execute_opencode_start(args)

# NEW
elif name == "opencode_project_start":
    return await self._execute_opencode_project_start(args)
elif name == "opencode_sandbox_create":
    return await self._execute_opencode_sandbox_create(args)
```

---

## Breaking Changes

### For End Users
- Tool names changed: `opencode_start` → `opencode_project_start`
- Parameter changed: `project_name` parameter removed, now auto-generated
- Response format: Now includes both `git_url` (primary key) and `project` (display name)

### Migration Guide for Users
```
OLD: opencode_start(project_name="my-repo", git_url="git@github.com:user/repo.git")
NEW: opencode_project_start(git_url="git@github.com:user/repo.git")
     # project_name auto-generated as "user-repo"
```

---

## Testing Plan

### Unit Tests
- [ ] Test all tool schemas are valid
- [ ] Test parameter validation (required fields, patterns)
- [ ] Test execution methods call manager correctly

### Integration Tests
- [ ] `opencode_project_start` creates project with git_url
- [ ] `opencode_project_list` returns correct format with git_url
- [ ] `opencode_sandbox_create` creates worktree successfully
- [ ] `opencode_sandbox_list` shows created worktrees
- [ ] `opencode_sandbox_delete` removes worktree
- [ ] Error handling for invalid git URLs
- [ ] Error handling for duplicate worktree names

### End-to-End Tests
- [ ] Start project → Create sandbox → Delete sandbox → Stop project
- [ ] List projects shows git_url and generated project_name
- [ ] Multiple worktrees per project work correctly

---

## Implementation Order

1. ✅ Update tool definitions (rename, add git_url parameter)
2. ✅ Add new sandbox tool definitions
3. ✅ Update execution method signatures
4. ✅ Add new sandbox execution methods
5. ✅ Update routing in execute()
6. ✅ Test all tools manually
7. ✅ Update user-facing documentation

---

## Rollout Strategy

### Option A: Breaking Change (Recommended)
- Remove old tools completely
- Users must update to new tool names
- Clean break, no confusion
- Document migration path clearly

### Option B: Deprecation Period
- Keep old tools with deprecation warnings
- Add new tools alongside
- Remove old tools in future release
- More work to maintain

**Recommendation:** Option A - Clean break. Phase 3 is a major refactor, better to do it all at once.
