# OpenCode Manager - Terminology Guide

**Last Updated**: 2026-02-06

## Core Concepts

### Project (Managed OpenCode Instance)

**Definition**: A managed OpenCode instance running for a specific Git repository.

**Simple Model**:
```
1 Project = 1 Git Repo = 1 OpenCode Instance = 1 Running Process
```

**NOT to be confused with**:
- ❌ "Session" in OpenCode/CLI agents (that's conversation history JSON)
- ❌ Multiple agents accessing the same repo (risky, race conditions)
- ❌ Runtime sessions that live only during execution

**What a Project IS**:
- ✅ A managed, persistent OpenCode instance
- ✅ Tied to a specific Git repository
- ✅ Has its own isolated sandbox directory
- ✅ Has its own OpenCode process (unique port)
- ✅ Registered with global MCP tool as a server

### Project ID

**Definition**: The unique identifier used consistently across all configurations.

**Format**: `project-name` (lowercase, hyphens for spaces)

**Example**: `personal-update-version-of-chatmcp-client`

**Used in**:
1. Manager state file (`opencode-state.json`) as dictionary key
2. MCP tool servers config (`opencode-mcp-tool-servers.json`) as server `id`
3. Sandbox directory path (`~/.memory/opencode-sandboxes/{project_id}`)
4. Log files (`{project_id}-opencode.log`)
5. PID files (`{sandbox_dir}/opencode.pid`)

**Consistency Rule**: The same Project ID must be used everywhere. This is enforced by the ConfigManager.

### Project Title

**Definition**: Human-readable display name for the project.

**Format**: Title Case with spaces

**Example**: `Personal Update Version Of Chatmcp Client`

**Used in**:
- MCP tool servers config (`title` field)
- UI displays (if any)

**Generated from**: Project ID (capitalize and replace hyphens with spaces)

### Session (OpenCode/CLI Context)

**Definition**: Conversation history between user and LLM in OpenCode or CLI agents.

**What it contains**:
- JSON array of messages (user/assistant exchanges)
- Timestamps
- Session metadata

**Lifecycle**: Lives during runtime, persisted to OpenCode's internal storage

**IMPORTANT**: This is **NOT** what we manage in the OpenCode Manager. OpenCode handles its own sessions internally. We manage the **running instance** (Project), not the conversations.

### Global MCP Tool

**Definition**: Single shared MCP server that routes requests to all managed Projects.

**Port**: 3005 (configurable via `GLOBAL_MCP_TOOL_PORT`)

**Architecture**: N:1 (Many Projects → One MCP Tool)

**Purpose**:
- Central entry point for MCP clients
- Routes tool calls to appropriate Project based on `server` parameter
- Auto-reloads config when Projects are added/removed

## Simple Model Summary

```
┌─────────────────────────────────────────────────┐
│  MCP Client (Claude Desktop, etc.)              │
└─────────────────┬───────────────────────────────┘
                  │ http://localhost:3005
                  │
┌─────────────────▼───────────────────────────────┐
│  Global MCP Tool (Port 3005)                    │
│  - Routes requests to Projects                  │
│  - Watches servers config for changes           │
└─────────────────┬───────────────────────────────┘
                  │
        ┌─────────┴─────────┬─────────────┐
        │                   │             │
┌───────▼────────┐ ┌────────▼──────┐ ┌───▼────────┐
│ Project A      │ │ Project B     │ │ Project C  │
│ Repo: chatmcp  │ │ Repo: web-app │ │ Repo: api  │
│ Port: 4104     │ │ Port: 4105    │ │ Port: 4106 │
│ PID: 2387554   │ │ PID: ...      │ │ PID: ...   │
└────────────────┘ └───────────────┘ └────────────┘
```

**Key Points**:
- Each Project = 1 repo = 1 OpenCode instance = 1 process
- All Projects share the same global MCP tool (port 3005)
- Projects are isolated (different ports, different sandboxes)
- No multiple agents accessing the same repo (prevents race conditions)

## Future Considerations

### OS-like Permissions (Future)

In the future, we could support multiple agents per repo with permission model:
- One agent: read/write access
- Other agents: read-only access
- Managed by a lock/permission system

**Current**: NOT IMPLEMENTED - keep it simple (1:1 mapping)

### Naming Convention (Suggested)

When creating Projects, use a consistent naming scheme:

**Pattern**: `{purpose}-{repo-name}`

**Examples**:
- `personal-chatmcp-client` - Personal fork of chatmcp
- `work-api-server` - Work project API server
- `experiment-new-feature` - Experimental branch

**Benefits**:
- Easy to identify purpose at a glance
- Groups related projects (all "work-*" projects)
- Human-readable without looking up details

## Terminology Quick Reference

| Term | Meaning | Example |
|------|---------|---------|
| **Project** | Managed OpenCode instance for a repo | `personal-update-version-of-chatmcp-client` |
| **Project ID** | Unique identifier (kebab-case) | `personal-update-version-of-chatmcp-client` |
| **Project Title** | Human-readable name (Title Case) | `Personal Update Version Of Chatmcp Client` |
| **Session** | OpenCode's conversation history (NOT what we manage) | JSON file with user/LLM messages |
| **Global MCP Tool** | Shared MCP server (port 3005) | Single instance serving all Projects |
| **Sandbox** | Isolated directory for Project's repo | `~/.memory/opencode-sandboxes/{project_id}` |
| **Instance** | Running OpenCode process | PID 2387554 on port 4104 |

## What We Do vs What OpenCode Does

### OpenCode Manager (Us)

- ✅ Start/stop OpenCode **processes** (instances)
- ✅ Manage **Projects** (1 repo = 1 instance)
- ✅ Health monitoring
- ✅ Process lifecycle (PID tracking, restart, etc.)
- ✅ Config synchronization (Manager ↔ MCP Tool)
- ✅ Sandbox isolation

### OpenCode (Them)

- ✅ Manage **sessions** (conversation history)
- ✅ Execute code operations (file read/write, search, etc.)
- ✅ AI integration (send messages to LLM)
- ✅ Session persistence and forking
- ✅ Internal state management

**Clear Boundary**: We manage the **container** (running instance), they manage the **content** (conversations, files, AI operations).

## Avoiding Confusion

### ❌ DON'T Say:
- "OpenCode session" (when you mean the running process)
- "Start a session" (when you mean start a Project)
- "Session management" (when you mean Project lifecycle)

### ✅ DO Say:
- "OpenCode Project" or "Managed Project"
- "Start a Project" or "Start OpenCode instance"
- "Project lifecycle management"
- "OpenCode conversation" or "OpenCode session history" (when referring to the chat logs)

## Agent Manager Pattern

The OpenCode Manager is the first implementation of the **Agent Manager Pattern**.

**Pattern**: Manage AI agent instances with lifecycle control, health monitoring, and MCP integration.

**Reusable for**:
- Browser automation agents
- Database query agents
- API testing agents
- File watchers
- Code analysis agents
- etc.

**Core Components**:
1. State Manager (tracks agent instances)
2. Process Manager (start/stop/health check)
3. Config Manager (sync with global MCP tool)
4. Global MCP Tool (single entry point for all agents)

**Key Principle**: 1 Agent Instance = 1 Process = 1 Configuration Entry = 1 Consistent ID

---

*This terminology guide ensures consistency across documentation, code, and communication.*
