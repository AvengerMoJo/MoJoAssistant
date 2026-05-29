# OpenCode Web API Specification

**Version:** 0.0.3
**Description:** opencode api
**Generated:** 2026-02-10

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Core Concepts](#core-concepts)
4. [API Endpoints Summary](#api-endpoints-summary)
5. [Key Schemas](#key-schemas)
6. [Important Findings](#important-findings)

---

## Overview

OpenCode exposes a RESTful HTTP API for managing AI coding sessions, projects, and workspaces.

**Base URL:** `http://hostname:port` (default port varies per instance)

## Authentication

All API endpoints require HTTP Basic Authentication:

```bash
Authorization: Basic base64(username:password)
```

Where:
- `username` = `"opencode"` (fixed)
- `password` = Server password (set via `OPENCODE_SERVER_PASSWORD` env var)

Example:
```bash
curl -u "opencode:2400" http://localhost:4104/session
# Or with explicit header:
curl -H "Authorization: Basic b3BlbmNvZGU6MjQwMA==" http://localhost:4104/session
```

## Core Concepts

### Project
A **Project** represents a Git repository. OpenCode identifies projects by:
- Git remote URL (hashed to create `projectID`)
- Projects persist across OpenCode restarts
- Sessions belong to projects, not specific directories
- **Key insight:** Same repo in different directories = same project

### Session
A **Session** is a conversation with AI about a project:
- Sessions are **project-scoped** (visible from any worktree of that project)
- Can be forked at any message to create conversation branches
- Persist indefinitely in OpenCode's data directory
- **Directory field in session:** Where session was created, but visible from all worktrees

### Worktree (Sandbox)
A **Worktree** is an isolated working directory for a project:
- Uses Git worktrees under the hood (`git worktree add`)
- Multiple worktrees share the same project/session history
- Useful for testing changes without affecting main branch
- **Native OpenCode feature** via `/experimental/worktree` endpoints

### Message
A **Message** is a single user prompt or AI response within a session:
- Can contain multiple parts (text, images, files)
- AI responses may include tool calls and file modifications
- Can be reverted/unreverted

---

## API Endpoints Summary

### Project Management
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/project` | GET | List all projects OpenCode has worked with |
| `/project/current` | GET | Get currently active project |
| `/project/{projectID}` | PATCH | Update project metadata (name, icon, commands) |

### Session Management
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/session` | GET | List all sessions (filterable by directory, search, etc.) |
| `/session` | POST | Create new session |
| `/session/{sessionID}` | GET | Get session details |
| `/session/{sessionID}` | DELETE | Delete session permanently |
| `/session/{sessionID}` | PATCH | Update session (title, etc.) |
| `/session/{sessionID}/message` | GET | Get all messages in session |
| `/session/{sessionID}/message` | POST | Send message (streams AI response) |
| `/session/{sessionID}/fork` | POST | Fork session at a message |
| `/session/{sessionID}/abort` | POST | Abort active session |
| `/session/{sessionID}/share` | POST | Create shareable link |

### Worktree/Sandbox (Experimental)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/experimental/worktree` | POST | Create git worktree (sandbox) |
| `/experimental/worktree` | GET | List all worktrees |
| `/experimental/worktree` | DELETE | Remove worktree |
| `/experimental/worktree/reset` | POST | Reset worktree to default branch |

**Request Body for POST:**
```json
{
  "name": "sandbox-name",
  "startCommand": "optional-startup-script"
}
```

### Configuration
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/config` | GET | Get current config (model, providers, keybinds, etc.) |
| `/config` | PATCH | Update config (including model) |
| `/global/config` | GET | Get global config |
| `/global/config` | PATCH | Update global config |

**Example PATCH to change model:**
```bash
curl -X PATCH -u "opencode:2400" \
  -H "Content-Type: application/json" \
  -d '{"model": "google/gemini-2.5-flash"}' \
  http://localhost:4104/config
```

### Providers
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/provider` | GET | List all available AI providers and models |
| `/provider/auth` | GET | Get provider auth methods |
| `/config/providers` | GET | List configured providers |

### File Operations
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/find` | GET | Search text in files (ripgrep) |
| `/find/file` | GET | Find files by name/pattern |
| `/find/symbol` | GET | Find symbols via LSP |
| `/file` | GET | List files in directory |
| `/file/content` | GET | Read file content |
| `/file/status` | GET | Get git status of files |

### MCP Integration
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mcp` | GET | Get MCP server status |
| `/mcp` | POST | Add MCP server dynamically |
| `/mcp/{name}/connect` | POST | Connect MCP server |
| `/mcp/{name}/disconnect` | POST | Disconnect MCP server |
| `/experimental/resource` | GET | Get MCP resources |

### Other Important Endpoints
- `/global/health` - Health check
- `/vcs` - Get VCS info (branch, status)
- `/permission` - List/respond to AI permission requests
- `/question` - List/respond to AI questions
- `/agent` - List available agents
- `/command` - List available commands

---

## Key Schemas

### Project
```typescript
{
  id: string;           // Hash of git remote URL
  worktree: string;     // Main working directory
  vcs: "git";
  name?: string;        // Custom project name
  icon?: { color };
  commands?: {};
  time: { created, updated };
  sandboxes: string[];  // List of worktree paths
}
```

### Session
```typescript
{
  id: string;              // Session ID (ses_xxx)
  slug: string;            // Human-readable slug
  projectID: string;       // Links to project
  directory: string;       // Where session was created
  parentID?: string;       // For forked sessions
  title: string;
  version: string;         // OpenCode version
  time: { created, updated };
  summary?: { additions, deletions, files };
}
```

### Config
```typescript
{
  $schema?: string;
  model?: string;          // Current model (provider/model)
  provider?: {             // Custom provider configs
    [providerID]: {
      npm: string;
      name: string;
      models: {};
      options: {};
    }
  };
  mcp?: {                  // MCP server configs
    [name]: {
      type: "remote" | "stdio";
      url?: string;
      command?: string;
      enabled: boolean;
      headers?: {};
    }
  };
  agent?: {};              // Agent configurations
  keybinds?: {};           // Keyboard shortcuts
  // ... many more fields
}
```

### WorktreeCreateInput
```typescript
{
  name: string;           // Worktree name
  startCommand?: string;  // Optional startup script
}
```

---

## Important Findings

### 1. **Project Identity is Based on Git Remote**
- Two clones of the same repo = **same project ID**
- Sessions are visible across all clones/directories
- Can't create isolated projects for the same repo without different remotes

### 2. **Native Sandbox Support via Worktrees**
- OpenCode has built-in `/experimental/worktree` API
- Uses git worktrees (not separate clones)
- Designed for: one OpenCode instance → multiple worktrees per project
- **We were fighting this design** by creating separate clones

### 3. **Config is Per-Instance, Not Per-Project**
- `PATCH /config` updates runtime config for that OpenCode instance
- Changes don't persist to `~/.config/opencode/opencode.json`
- Each OpenCode process can have different model at runtime

### 4. **The `directory` Query Parameter**
- Most endpoints accept `?directory=` parameter
- Seems to be for filtering when OpenCode manages multiple projects
- **Unclear if this creates project isolation or just filtering**

### 5. **Sessions are Globally Visible**
- `GET /session` returns all sessions for the project
- No way to scope sessions to a specific worktree/sandbox
- This is **by design** - collaborate across worktrees

---

## Recommended Architecture

Based on the API spec, OpenCode is designed for:

```
MCP Client
  └─ OpenCode Manager (Python)
      └─ OpenCode Instance (per git repo)
          ├─ Main worktree
          ├─ Sandbox 1 (worktree)
          ├─ Sandbox 2 (worktree)
          └─ Sessions (project-wide)
```

**Not:**
```
Multiple OpenCode instances for the same repo
Multiple clones of the same repo
Expecting session isolation per clone
```

---

## Next Steps

See `docs/opencode-manager-redesign-plan.md` for implementation strategy.
