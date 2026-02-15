# OpenCode Manager User Guide

Welcome to the OpenCode Manager! This guide will help you get started with managing OpenCode projects through the MCP (Model Context Protocol) interface.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Core Concepts](#core-concepts)
3. [Common Workflows](#common-workflows)
4. [MCP Tools Reference](#mcp-tools-reference)
5. [Troubleshooting](#troubleshooting)
6. [Best Practices](#best-practices)

---

## Quick Start

### Prerequisites

1. **OpenCode installed**
   ```bash
   npm install -g @opencode/cli
   # Or check if already installed:
   which opencode
   ```

2. **Global configuration**
   ```bash
   # Create configuration directory
   mkdir -p ~/.memory

   # Copy template
   cp app/mcp/opencode/templates/opencode-manager.env.template ~/.memory/opencode-manager.env

   # Edit with your passwords
   vim ~/.memory/opencode-manager.env

   # Set secure permissions
   chmod 600 ~/.memory/opencode-manager.env
   ```

3. **Generate secure passwords**
   ```bash
   # OpenCode password
   openssl rand -hex 16

   # MCP bearer token
   openssl rand -hex 32
   ```

### Your First Project

1. **Start a project**
   ```
   Use tool: opencode_project_start
   Parameters:
     git_url: git@github.com:user/repo.git
   ```

2. **Get the SSH deploy key**
   ```
   Use tool: opencode_get_deploy_key
   Parameters:
     git_url: git@github.com:user/repo.git
   ```

3. **Add the key to GitHub**
   - Copy the public key from the response
   - Go to: https://github.com/user/repo/settings/keys
   - Click "Add deploy key"
   - Paste the key and save

4. **Verify the project is running**
   ```
   Use tool: opencode_project_status
   Parameters:
     git_url: git@github.com:user/repo.git
   ```

---

## Core Concepts

### Git URL as Primary Key

OpenCode Manager uses **git URLs** as the primary identifier for projects, not arbitrary project names.

**Why?** This aligns with OpenCode's native architecture where projects are identified by their git remote URL.

**Example:**
- ✅ Good: `git@github.com:anthropics/anthropic-quickstarts.git`
- ✅ Also works: `https://github.com/anthropics/anthropic-quickstarts`
- ❌ Bad: "my-project" (arbitrary names not used)

**Normalization:** All URLs are automatically normalized to SSH format with `.git` suffix:
```
https://github.com/user/repo → git@github.com:user/repo.git
```

### Project Names (Display Only)

Project names are **automatically generated** from git URLs for display purposes:

```
git@github.com:anthropics/anthropic-quickstarts.git
→ Project name: "anthropics-anthropic-quickstarts"
```

You don't need to specify project names - they're derived from the repository.

### Base Directories

Projects are cloned to **managed directories** by default:

```
~/.opencode-projects/{owner}-{repo}/
```

Example:
```
git@github.com:user/my-app.git
→ Base dir: ~/.opencode-projects/user-my-app/
```

### Sandboxes (Worktrees)

**Sandboxes** are git worktrees - isolated working directories that share the same .git database.

**Benefits:**
- Work on multiple branches simultaneously
- No need to stash changes when switching contexts
- Efficient (shared .git, separate working directory)

**Example:**
- Main worktree: `~/.opencode-projects/user-repo/` (main branch)
- Sandbox 1: `~/.opencode-projects/user-repo/worktrees/feature-auth/` (feature-auth branch)
- Sandbox 2: `~/.opencode-projects/user-repo/worktrees/bugfix/` (bugfix branch)

### Sessions

**Sessions** are project-scoped (not worktree-scoped). This means:
- Sessions are visible from all worktrees of the same project
- This is intentional - designed for collaboration
- You can start work in one worktree, switch to another, and continue the same conversation

---

## Common Workflows

### Workflow 1: Starting a New Project

**Scenario:** You want to start working on a GitHub repository.

1. **Start the project**
   ```
   Tool: opencode_project_start
   Input: git_url = "git@github.com:user/repo.git"
   ```

2. **Get the deploy key**
   ```
   Tool: opencode_get_deploy_key
   Input: git_url = "git@github.com:user/repo.git"
   ```

3. **Add key to GitHub**
   - Copy public key from response
   - Go to repository settings → Deploy keys
   - Add key with write access if needed

4. **Verify running**
   ```
   Tool: opencode_project_status
   Input: git_url = "git@github.com:user/repo.git"
   ```

**Result:** OpenCode server running on auto-assigned port, ready to use!

---

### Workflow 2: Working with Sandboxes

**Scenario:** You want to work on a feature branch without affecting your main branch.

1. **Create a sandbox**
   ```
   Tool: opencode_sandbox_create
   Input:
     git_url: "git@github.com:user/repo.git"
     name: "feature-auth"
     branch: "feature/authentication"
   ```

2. **List all sandboxes**
   ```
   Tool: opencode_sandbox_list
   Input: git_url = "git@github.com:user/repo.git"
   ```

3. **Work in the sandbox**
   - OpenCode automatically uses the sandbox directory
   - Your main worktree is unaffected
   - Sessions are shared across worktrees

4. **Clean up when done**
   ```
   Tool: opencode_sandbox_delete
   Input:
     git_url: "git@github.com:user/repo.git"
     name: "feature-auth"
   ```

**Tips:**
- Use descriptive sandbox names: "feature-x", "bugfix-y", "experiment"
- Delete sandboxes when done to keep things clean
- You can have multiple sandboxes per project

---

### Workflow 3: Managing Multiple Projects

**Scenario:** You work on several repositories.

1. **Start multiple projects**
   ```
   opencode_project_start(git_url: "git@github.com:user/frontend.git")
   opencode_project_start(git_url: "git@github.com:user/backend.git")
   opencode_project_start(git_url: "git@github.com:user/mobile.git")
   ```

2. **List all projects**
   ```
   Tool: opencode_project_list
   Returns: All projects with status, ports, directories
   ```

3. **Switch between projects**
   - Each project has its own OpenCode instance
   - Each runs on a different port (auto-assigned)
   - Use git_url to identify which project to interact with

4. **Stop unused projects**
   ```
   Tool: opencode_project_stop
   Input: git_url = "git@github.com:user/frontend.git"
   ```

**Resource Management:**
- Each project uses ~200-500 MB RAM
- Stop projects you're not actively using
- Use `opencode_project_list` to see what's running

---

### Workflow 4: Cleaning Up

**Scenario:** You want to clean up your environment.

1. **Detect duplicates**
   ```
   Tool: opencode_detect_duplicates

   Shows if same repository is running multiple times
   Recommends which instance to keep
   ```

2. **Clean up orphaned processes**
   ```
   Tool: opencode_cleanup_orphaned

   Finds processes marked as running but actually crashed
   Automatically updates state
   ```

3. **Stop all projects**
   ```
   Get list: opencode_project_list
   For each: opencode_project_stop(git_url)
   ```

---

## MCP Tools Reference

### Project Lifecycle (6 tools)

#### `opencode_project_start`
Start an OpenCode instance for a git repository.

**Parameters:**
- `git_url` (required): Git repository URL

**Returns:**
- `status`: "success" or "error"
- `project`: Display name (e.g., "user-repo")
- `git_url`: Normalized git URL
- `opencode_port`: Port number (e.g., 4100)
- `base_dir`: Project directory path
- `message`: Human-readable status

**Example:**
```json
{
  "git_url": "https://github.com/anthropics/anthropic-quickstarts"
}
```

---

#### `opencode_project_status`
Get status of a project.

**Parameters:**
- `git_url` (required): Git repository URL

**Returns:**
- Project status (running/stopped)
- Process details (PID, port)
- Base directory
- Worktree list

---

#### `opencode_project_stop`
Stop a running project.

**Parameters:**
- `git_url` (required): Git repository URL

**Returns:**
- Success/failure status
- Message

**Note:** This stops the OpenCode server but doesn't delete files.

---

#### `opencode_project_restart`
Restart a project.

**Parameters:**
- `git_url` (required): Git repository URL

**Returns:**
- New port (may change on restart)
- Status

---

#### `opencode_project_destroy`
Completely remove a project (stops and deletes files).

**Parameters:**
- `git_url` (required): Git repository URL

**Returns:**
- Success/failure status

**⚠️ Warning:** This deletes all project files! Use with caution.

---

#### `opencode_project_list`
List all projects.

**Parameters:** None

**Returns:**
- Array of projects with:
  - git_url
  - name
  - status (running/stopped)
  - port
  - base_dir

---

### Sandbox Management (4 tools)

#### `opencode_sandbox_create`
Create a git worktree (sandbox).

**Parameters:**
- `git_url` (required): Git repository URL
- `name` (required): Worktree name (unique per project)
- `branch` (optional): Branch to checkout
- `start_command` (optional): Command to run after creation

**Returns:**
- Worktree details (name, path, branch)

**Example:**
```json
{
  "git_url": "git@github.com:user/repo.git",
  "name": "feature-auth",
  "branch": "feature/authentication"
}
```

---

#### `opencode_sandbox_list`
List all sandboxes for a project.

**Parameters:**
- `git_url` (required): Git repository URL

**Returns:**
- Array of worktrees with paths and branches

---

#### `opencode_sandbox_delete`
Delete a sandbox.

**Parameters:**
- `git_url` (required): Git repository URL
- `name` (required): Worktree name

**Returns:**
- Success/failure status

---

#### `opencode_sandbox_reset`
Reset a sandbox to clean state.

**Parameters:**
- `git_url` (required): Git repository URL
- `name` (required): Worktree name

**Returns:**
- Success/failure status

---

### SSH & Configuration (3 tools)

#### `opencode_get_deploy_key`
Get SSH public key for a repository.

**Parameters:**
- `git_url` (required): Git repository URL

**Returns:**
- `public_key`: SSH public key content
- `public_key_path`: Path to .pub file
- `github_deploy_keys_url`: Direct link to add key on GitHub
- `instructions`: Step-by-step guide

**When to use:**
- After starting a new project
- When SSH authentication fails
- To verify which key is being used

---

#### `opencode_llm_config`
Get current LLM configuration.

**Parameters:** None

**Returns:**
- Current model settings
- Available models

---

#### `opencode_llm_set_model`
Set the default LLM model.

**Parameters:**
- `model` (required): Model name (e.g., "claude-opus-4")

**Returns:**
- Success/failure status

---

### Diagnostic Tools (2 tools)

#### `opencode_detect_duplicates`
Find duplicate projects (same repository running multiple times).

**Parameters:** None

**Returns:**
- List of duplicates
- Recommendations on which to keep

**When to use:**
- To optimize resource usage
- When confused about multiple instances
- During cleanup

---

#### `opencode_cleanup_orphaned`
Clean up orphaned processes.

**Parameters:** None

**Returns:**
- List of orphaned processes
- Cleaned projects

**When to use:**
- After crashes or unexpected shutdowns
- When state seems inconsistent
- During regular maintenance

---

## Troubleshooting

### Common Issues

#### "Project not found"

**Problem:** You tried to operate on a project that doesn't exist.

**Solutions:**
1. Check the git_url is correct (case-sensitive)
2. List all projects: `opencode_project_list`
3. Start the project if needed: `opencode_project_start`

---

#### "SSH key does not have access"

**Problem:** OpenCode can't clone the repository.

**Solutions:**
1. Get the deploy key: `opencode_get_deploy_key`
2. Add it to GitHub: Settings → Deploy keys
3. Enable write access if you need to push
4. Test SSH: `ssh -T git@github.com`

---

#### "Port already in use"

**Problem:** The requested port is occupied.

**Solutions:**
1. Let OpenCode auto-assign a port (don't specify)
2. Check what's using the port: `lsof -i :4100`
3. Stop conflicting service or use different port

---

#### "OpenCode binary not found"

**Problem:** OpenCode isn't installed or not in PATH.

**Solutions:**
1. Install: `npm install -g @opencode/cli`
2. Verify: `which opencode`
3. Add to PATH if needed
4. Set OPENCODE_BIN in global config if in custom location

---

#### "Configuration error"

**Problem:** Global config is missing or invalid.

**Solutions:**
1. Check file exists: `ls ~/.memory/opencode-manager.env`
2. Verify permissions: `chmod 600 ~/.memory/opencode-manager.env`
3. Ensure passwords are set (not CHANGE_ME_REQUIRED)
4. Generate new passwords:
   ```bash
   openssl rand -hex 16  # OPENCODE_PASSWORD
   openssl rand -hex 32  # MCP_BEARER_TOKEN
   ```

---

#### "Worktree already exists"

**Problem:** Trying to create a worktree with existing name.

**Solutions:**
1. List existing: `opencode_sandbox_list`
2. Use a different name
3. Delete old worktree if not needed: `opencode_sandbox_delete`

---

### Getting Help

1. **Check status first**
   ```
   opencode_project_status(git_url)
   opencode_project_list()
   ```

2. **Run diagnostics**
   ```
   opencode_detect_duplicates()
   opencode_cleanup_orphaned()
   ```

3. **Check logs**
   - OpenCode logs: Usually in project directory
   - MoJoAssistant logs: Check console output

4. **Report issues**
   - GitHub: https://github.com/anthropics/claude-code/issues
   - Include error messages and stack traces
   - Mention your setup (OS, OpenCode version)

---

## Best Practices

### Naming Conventions

**Sandbox names:**
- Use descriptive prefixes: `feature-`, `bugfix-`, `experiment-`
- Keep them short but meaningful
- Example: `feature-auth`, `bugfix-login`, `experiment-ui`

**Git URLs:**
- Always use SSH format if possible (better security)
- OpenCode handles HTTPS → SSH conversion automatically

### Resource Management

**Stop unused projects:**
```
# Before starting work:
opencode_project_list()

# Stop what you're not using:
opencode_project_stop(git_url: "...")
```

**Clean up sandboxes:**
```
# After merging a feature:
opencode_sandbox_delete(git_url, name: "feature-xyz")
```

**Regular maintenance:**
```
# Weekly/monthly:
opencode_detect_duplicates()
opencode_cleanup_orphaned()
```

### Security

**Protect your keys:**
- Never commit `.env` files
- Use `chmod 600` for all config files
- Rotate passwords periodically
- Use read-only deploy keys when possible

**SSH keys:**
- One key per repository (automatically managed)
- Keys stored in `~/.memory/opencode-keys/`
- Revoke unused keys on GitHub

### Performance

**Memory usage:**
- Each project: ~200-500 MB RAM
- Stop projects when not in use
- Use sandboxes instead of multiple clones

**Disk space:**
- Git worktrees share .git (efficient)
- Each worktree: ~size of working directory only
- Clean up old sandboxes regularly

---

## Examples

### Example 1: Feature Development

```
# 1. Start the project
opencode_project_start(git_url: "git@github.com:company/app.git")

# 2. Create sandbox for feature
opencode_sandbox_create(
  git_url: "git@github.com:company/app.git",
  name: "feature-payment",
  branch: "feature/payment-integration"
)

# 3. Work on the feature in OpenCode
# (OpenCode automatically uses the sandbox)

# 4. After merging, clean up
opencode_sandbox_delete(
  git_url: "git@github.com:company/app.git",
  name: "feature-payment"
)
```

### Example 2: Bug Investigation

```
# 1. List projects to find the right one
opencode_project_list()

# 2. Create sandbox for investigation
opencode_sandbox_create(
  git_url: "git@github.com:company/app.git",
  name: "debug-issue-123",
  branch: "main"  # Start from main
)

# 3. Investigate and fix in sandbox
# 4. When done, either keep or delete
opencode_sandbox_delete(...)
```

### Example 3: Multi-Project Setup

```
# Morning routine:
# 1. Start all your projects
opencode_project_start(git_url: "git@github.com:company/frontend.git")
opencode_project_start(git_url: "git@github.com:company/backend.git")
opencode_project_start(git_url: "git@github.com:company/docs.git")

# 2. Create sandboxes for today's work
opencode_sandbox_create(
  git_url: "git@github.com:company/frontend.git",
  name: "sprint-tasks"
)

# Evening routine:
# 3. Stop what you're not using overnight
opencode_project_stop(git_url: "git@github.com:company/docs.git")
```

---

## Advanced Topics

### Custom Base Directories

By default, projects go to `~/.opencode-projects/{name}/`. You can customize this per-project in the .env file (not yet exposed via MCP tools).

### Global MCP Tool

OpenCode Manager uses a "global MCP tool" architecture:
- One `opencode-mcp-tool` routes to N OpenCode servers
- Automatically started when first project starts
- Automatically stopped when last project stops

### State Files

State is persisted in:
- `~/.memory/opencode-state.json` - Project state
- `~/.memory/opencode-mcp-tool-servers.json` - Server config

These are automatically managed - you shouldn't need to edit them manually.

---

## Changelog

### Phase 5 (Current)
- Duplicate detection
- Orphaned process cleanup
- Improved error messages with suggestions
- Comprehensive unit tests
- This user guide

### Phase 4
- SSH deploy key management
- `opencode_get_deploy_key` tool

### Phase 3
- MCP tools renamed (git_url-based)
- Sandbox management tools added

### Phase 2
- Git worktree support
- Sandbox operations

### Phase 1
- git_url as primary key
- Auto-generated project names
- State file migration

---

**Happy coding with OpenCode Manager!** 🚀
