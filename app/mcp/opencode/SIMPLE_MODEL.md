# OpenCode Manager - Simple Model (v1.1 Beta)

**Philosophy**: Keep it simple. OpenCode Manager = Process Lifecycle Manager. Nothing more.

## The Simple Rule

```
1 Project = 1 Git Repo = 1 OpenCode Process = 1 Project ID
```

## What OpenCode Manager Does (ONLY)

```
┌─────────────────────────────────────────┐
│      OpenCode Manager                   │
│                                         │
│  1. Start OpenCode process              │
│  2. Stop OpenCode process               │
│  3. Check if process is healthy         │
│  4. Register with global MCP tool       │
│                                         │
│  That's ALL.                            │
└─────────────────────────────────────────┘
```

**NOT the Manager's job**:
- ❌ File operations (OpenCode does this)
- ❌ Tool definitions (opencode-mcp-tool does this)
- ❌ Sessions (OpenCode does this)
- ❌ MCP protocol (opencode-mcp-tool does this)
- ❌ What the agent actually does (OpenCode does this)

## Clean Separation of Concerns

```
┌──────────────────────────────────────────────────────────┐
│                    MCP Client                            │
│            (Claude Desktop, chatmcp, etc.)               │
└────────────────────┬─────────────────────────────────────┘
                     │
                     │ "I want to list files"
                     │
┌────────────────────▼─────────────────────────────────────┐
│              Global MCP Tool (Port 3005)                 │
│                                                          │
│  Job: Route MCP requests to the right agent              │
│  - "Which server? Ah, project-a on port 4104"           │
│  - Proxy the request there                               │
└────────────────────┬─────────────────────────────────────┘
                     │
                     │ Forward request
                     │
┌────────────────────▼─────────────────────────────────────┐
│              OpenCode (Port 4104)                        │
│                                                          │
│  Job: Execute the actual work                            │
│  - List files in repo                                    │
│  - Read file content                                     │
│  - Search content                                        │
│  - Manage sessions (conversation history)                │
│  - Everything about the AI agent's functionality         │
└──────────────────────────────────────────────────────────┘

                     ↑
                     │
                     │ "Is it alive? Yes/No"
                     │
┌────────────────────┴─────────────────────────────────────┐
│              OpenCode Manager                            │
│                                                          │
│  Job: Keep OpenCode process running                      │
│  - Start: Launch OpenCode on port 4104                   │
│  - Health: Check if it responds                          │
│  - Stop: Kill the process                                │
│  - Register: Tell MCP tool about port 4104               │
│                                                          │
│  Does NOT care what OpenCode does with requests          │
└──────────────────────────────────────────────────────────┘
```

## Manager's Simple API

```python
manager = OpenCodeManager()

# Start a project (launches OpenCode process)
await manager.start_project(
    project_name="my-project",
    git_url="git@github.com:user/repo.git",
    ssh_key_path="/path/to/key"
)
# → OpenCode process started on port 4104
# → Registered with MCP tool
# → Done. Manager's job complete.

# Check health (is process alive?)
result = await manager.list_projects()
# → Returns: running=True, port=4104

# Stop project (kill the process)
await manager.stop_project("my-project")
# → Process killed
# → MCP tool notified
# → Done.

# Delete project (kill + remove sandbox)
await manager.delete_project("my-project")
# → Process killed
# → Sandbox deleted
# → Removed from MCP tool
# → Done.
```

**That's the entire Manager API. Simple.**

## What Happens After Start

```
Time: T0
Manager: "Starting OpenCode on port 4104..."
Manager: "Process started, PID 2387554"
Manager: "Waiting for health check..."
Manager: "Health check passed!"
Manager: "Telling MCP tool about port 4104..."
Manager: "Done. My job is finished."

Time: T0 + 1 second
MCP Tool: "Config reloaded, I now know about port 4104"

Time: T0 + 5 seconds
MCP Client: "List files in my-project"
MCP Tool: "Routing to port 4104"
OpenCode: "Here are your files: [...]"

Time: T0 + 10 seconds
MCP Client: "Read README.md"
MCP Tool: "Routing to port 4104"
OpenCode: "Here's the content: [...]"

Manager: (does nothing, just monitors process is still alive)
```

**Manager's responsibility ends after start + registration.**

## The 1:1 Model

```
Project ID: my-awesome-project

Maps to:
├─ Git Repo: git@github.com:user/awesome.git
├─ OpenCode Process: PID 2387554
├─ OpenCode Port: 4104
├─ Sandbox: ~/.memory/opencode-sandboxes/my-awesome-project/
├─ MCP Server ID: my-awesome-project
└─ Logs: ~/.memory/opencode-logs/my-awesome-project-opencode.log

One ID, consistent everywhere.
One repo, one process, one entry in MCP config.
Simple.
```

## Why This is Clean

### Before (Confused):
```
"OpenCode Manager manages file operations and sessions and..."
"Wait, does it handle MCP protocol?"
"What about tool definitions?"
"Who's responsible for what?"
```

### After (Clear):
```
Manager: "I start/stop processes. That's all."
MCP Tool: "I route requests. That's all."
OpenCode: "I do the actual work. That's all."
```

**Each component has ONE job.**

## Agent Manager Pattern

This pattern is reusable for ANY AI agent:

```python
class AgentManager:
    """
    Generic agent lifecycle manager

    Responsibilities:
    1. Start agent process
    2. Stop agent process
    3. Health monitoring
    4. Register with global MCP tool

    NOT responsible for:
    - What the agent does
    - What tools it exposes
    - How it processes requests
    """

    def start_agent(agent_id, config):
        # Launch the agent process
        # Wait for health check
        # Register with MCP tool
        # Done

    def stop_agent(agent_id):
        # Kill the process
        # Update MCP tool
        # Done
```

**Applicable to**:
- OpenCode Manager ✅ (implemented)
- Browser automation agent
- Database query agent
- API testing agent
- File watcher agent
- Code analysis agent
- etc.

**Always the same pattern**: Manage the process, not the functionality.

## Current State (Clean)

**What's Running**:
```
Global MCP Tool: PID 2386013, Port 3005
  └─ Knows about: 1 project

Project: personal-update-version-of-chatmcp-client
  Process: PID 2387554
  Port: 4104
  Status: running
  Repo: git@github.com:AvengerMoJo/chatmcp.git
```

**What's Working**:
- ✅ Manager starts/stops OpenCode process
- ✅ Manager monitors health
- ✅ Manager registers with MCP tool
- ✅ MCP tool auto-reloads config
- ✅ Clean 1:1 mapping (1 ID everywhere)
- ✅ Process isolation (each project gets own port/sandbox)

**What's NOT the Manager's Concern**:
- ✅ File operations (OpenCode handles)
- ✅ Tool definitions (opencode-mcp-tool handles)
- ✅ MCP protocol (opencode-mcp-tool handles)
- ✅ Sessions (OpenCode handles)

## Next Steps

### 1. Test with Real MCP Client
```
Connect Claude Desktop to http://localhost:3005
Verify it can use OpenCode's tools
Confirm full chain works
```

### 2. Add Second Project (Test Isolation)
```python
await manager.start_project(
    project_name="second-project",
    git_url="git@github.com:user/other-repo.git",
    ssh_key_path="/path/to/key"
)
```

Verify:
- Gets different port (4105)
- Different sandbox
- Both registered with MCP tool
- MCP client can use both via different server IDs

### 3. Document as Template

Use this as the Agent Manager pattern template for future agents.

## Summary

**OpenCode Manager = Process Lifecycle Manager**

```
Start → Health Check → Register → Monitor
Stop  → Unregister → Cleanup

That's all.
```

Clean, simple, reusable.

---

*Do one thing and do it well.*
