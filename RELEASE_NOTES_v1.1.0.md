# MoJoAssistant v1.1.0 Release Notes

**Release Date**: February 9, 2026
**Tag**: v1.1.0
**Status**: Production Ready

---

## 🎯 Overview

**MoJoAssistant v1.1.0 introduces the OpenCode Manager extension** - a production-ready system for orchestrating and managing OpenCode AI agent instances.

This release focuses on extending MoJoAssistant's capabilities to work seamlessly with external AI agents (OpenCode), with a roadmap to support additional agents like OpenClaw.

---

## 🤖 What is OpenCode Manager?

OpenCode Manager is an **AI agent orchestration layer** that enables you to:

1. **Run multiple OpenCode instances** - Each project gets its own isolated OpenCode server
2. **Manage lifecycle programmatically** - Start, stop, restart via MCP tools
3. **Integrate with MoJoAssistant** - Seamlessly connect AI agents to your memory system
4. **Future-proof architecture** - Ready to support OpenClaw and other agents

### Architecture

```
MoJoAssistant Core
    ↓
OpenCode Manager (Extension)
    ↓
┌─────────────────────────────────────┐
│  OpenCode Instance 1 (port 4100)   │  ← AI Agent 1
│  OpenCode Instance 2 (port 4101)   │  ← AI Agent 2
│  OpenCode Instance 3 (port 4102)   │  ← AI Agent 3
│         ↓                           │
│  Global MCP Tool (port 3005)         │  ← Unified MCP Interface
│         ↓                           │
│  AI Clients (Claude Desktop, etc.)   │
└─────────────────────────────────────┘
```

---

## 🚀 What's New in v1.1.0

### 1. OpenCode Manager - Production Ready

**Core Features:**

#### Multi-Project Management
```bash
# Run multiple OpenCode instances for different projects
opencode_start blog-api git@github.com:user/blog-api.git
opencode_start mobile-app git@github.com:user/mobile-app.git
opencode_start backend-service git@github.com:user/backend.git

# Each gets isolated OpenCode AI agent
```

#### N:1 Architecture - Unified MCP Interface
```
Before (1:1):
  Project 1 → MCP Tool 1 (port 5100)
  Project 2 → MCP Tool 2 (port 5101)
  Project 3 → MCP Tool 3 (port 5102)

Now (N:1):
  Project 1 ─┐
  Project 2 ─┼→ Global MCP Tool (port 3005)
  Project 3 ─┘

Benefits:
✅ Single port (3005) for all projects
✅ Unified configuration
✅ Efficient resource usage
✅ Centralized control
```

#### Process Lifecycle Management
```bash
# Start - Bootstrap new project with OpenCode agent
opencode_start my-project git@github.com:user/repo.git

# Status - Check OpenCode and MCP tool status
opencode_status my-project

# Restart - Stop and start with same configuration
opencode_restart my-project

# Stop - Graceful shutdown
opencode_stop my-project

# List - All managed projects
opencode_list
```

### 2. SSH Key Management

**Per-Project SSH Deploy Keys:**
- ✅ Auto-generated using `ssh-keygen`
- ✅ Isolated per project (no cross-contamination)
- ✅ Stored securely in `~/.memory/opencode-keys/`
- ✅ Automatic deployment to Git repositories

```bash
# Key locations
~/.memory/opencode-keys/project1-deploy
~/.memory/opencode-keys/project2-deploy
~/.memory/opencode-keys/project3-deploy
```

### 3. Global Configuration

**Single Configuration File**: `~/.memory/opencode-manager.env`

```env
# Paths to external AI agents
OPENCODE_MCP_TOOL_PATH=/path/to/opencode-mcp-tool
OPENCODE_BIN=/path/to/opencode

# Security credentials
OPENCODE_SERVER_PASSWORD=your-password
GLOBAL_MCP_BEARER_TOKEN=your-token

# Port configuration
GLOBAL_MCP_TOOL_PORT=3005
```

### 4. State Persistence

**Projects Survive System Restarts:**
```bash
# System restart
sudo reboot

# Projects automatically resume
opencode_status my-project
# → Running (recovered from persistent state)
```

**State Files:**
- `~/.memory/opencode-state.json` - Project states
- `~/.memory/opencode-mcp-tool-servers.json` - Server configuration

### 5. Health Monitoring & Auto-Recovery

**Automatic Health Checks:**
- ✅ Periodic OpenCode instance health checks
- ✅ Periodic MCP tool health checks
- ✅ Auto-restart on failure
- ✅ Detailed logging for troubleshooting

### 6. Development Tools

**Hot Reload Support:**
```bash
# Development server with auto-reload
./run_dev.sh

# Or with file watching
./run_dev_watch.sh
```

---

## 🔧 Available MCP Tools

| Tool | Description | Usage |
|------|-------------|---------|
| `opencode_start` | Bootstrap new OpenCode project | `opencode_start <name> <git_url>` |
| `opencode_stop` | Stop OpenCode project | `opencode_stop <name>` |
| `opencode_restart` | Restart OpenCode project | `opencode_restart <name>` |
| `opencode_status` | Get project status | `opencode_status <name>` |
| `opencode_list` | List all projects | `opencode_list` |
| `opencode_mcp_restart` | Restart global MCP tool | `opencode_mcp_restart` |
| `opencode_mcp_status` | Get MCP tool status | `opencode_mcp_status` |
| `opencode_llm_config` | Get/set LLM configuration | `opencode_llm_config` |

---

## 🏗️ Architecture Deep Dive

### N:1 Architecture

**Why N:1?**

Efficient resource management and unified control:

1. **Port Management**: Single port (3005) instead of multiple ports
2. **Configuration**: Single `opencode-mcp-tool-servers.json` file
3. **Resource Usage**: One MCP tool process instead of N processes
4. **Routing**: Dynamic server selection based on requests

**Server Configuration:**
```json
{
  "version": "1.0",
  "servers": [
    {
      "id": "blog-api",
      "title": "Blog API",
      "description": "OpenCode server for blog-api",
      "url": "http://127.0.0.1:4100",
      "password": "2400",
      "status": "active",
      "added_at": "2026-02-09T12:00:00Z",
      "ssh_key_path": "/home/user/.memory/opencode-keys/blog-api-deploy",
      "git_url": "git@github.com:user/blog.git",
      "sandbox_dir": "/home/user/.memory/opencode-sandboxes/blog-api"
    }
  ],
  "default_server": "blog-api"
}
```

### Project Isolation

**Each project gets isolated sandbox:**
```
~/.memory/opencode-sandboxes/
├── project1/
│   ├── repo/              # Cloned git repository
│   ├── .env              # Project-specific env (no passwords)
│   ├── opencode.pid       # OpenCode process ID
│   └── .gitignore        # Protects .env
├── project2/
│   ├── repo/
│   ├── .env
│   ├── opencode.pid
│   └── .gitignore
└── project3/
    ├── repo/
    ├── .env
    ├── opencode.pid
    └── .gitignore
```

---

## 📋 Bug Fixes

| Issue | Impact | Fix |
|-------|---------|------|
| `active_project_count` not incrementing | Global MCP tool wouldn't start after all projects stopped | Added logic to increment count when restarting stopped projects |
| Built-in models missing in LLM config | Can't use OpenCode built-in providers | Query `opencode models` CLI to get all models |
| Redundant OpenCode tools | Confusing tool names | Consolidated to essential tools |
| Hot reload broken | Development workflow interrupted | Fixed with watchfiles alternative |
| PID tracking issues | Stale processes not detected | Improved process lifecycle management |

---

## 🚀 Quick Start (5 Minutes)

### Prerequisites

- Python 3.9+
- Git
- OpenCode CLI installed (`npm install -g opencode`)
- opencode-mcp-tool repository cloned locally

### Installation

```bash
# 1. Clone MoJoAssistant
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create global configuration
cp app/mcp/opencode/templates/opencode-manager.env.template ~/.memory/opencode-manager.env
chmod 600 ~/.memory/opencode-manager.env

# 4. Edit configuration
nano ~/.memory/opencode-manager.env
```

**Configuration (`~/.memory/opencode-manager.env`):**
```env
# Paths to external AI agents
OPENCODE_MCP_TOOL_PATH=/home/user/Development/Sandbox/opencode-mcp-tool
OPENCODE_BIN=/home/user/.bun/install/global/node_modules/opencode-linux-x64/bin/opencode

# Security credentials
OPENCODE_SERVER_PASSWORD=your-strong-password
GLOBAL_MCP_BEARER_TOKEN=your-bearer-token

# Port (optional, defaults to 3005)
GLOBAL_MCP_TOOL_PORT=3005
```

### First Project

```bash
# Start your first OpenCode project
opencode_start my-project git@github.com:user/repo.git

# What happens:
# → Generates SSH key: ~/.memory/opencode-keys/my-project-deploy
# → Clones repository to: ~/.memory/opencode-sandboxes/my-project/repo
# → Starts OpenCode on port: 4100 (or next available)
# → Creates PID file for process tracking
# → Adds to global MCP config: ~/.memory/opencode-mcp-tool-servers.json
# → Starts global MCP tool on port 3005

# Check status
opencode_status my-project
```

---

## 📚 Documentation

**Complete documentation available in `app/mcp/opencode/`:**

| File | Description |
|------|-------------|
| `README.md` | Comprehensive feature documentation |
| `ARCHITECTURE_N_TO_1.md` | N:1 architecture deep dive |
| `CONFIGURATION.md` | Setup and configuration guide |
| `GLOBAL_CONFIG_MIGRATION.md` | Migration from v1.0 |
| `SSH_KEY_ARCHITECTURE.md` | SSH key management |
| `TEST_RESULTS_v1.1_BETA.md` | Test results |
| `SETUP_GLOBAL_CONFIG.md` | Step-by-step setup |

---

## ✅ Testing Results

**All 10 comprehensive tests passed:**

1. ✅ Both projects running, MCP tool running
2. ✅ Stop one project (MCP stays running)
3. ✅ Stop last project (MCP auto-stops)
4. ✅ Restart first project (MCP starts)
5. ✅ Restart second project (count increments correctly)
6. ✅ Restart running project (count unchanged)
7. ✅ Stop one, then restart (count correct)
8. ✅ Manual MCP restart
9. ✅ Manual MCP stop (with active projects)
10. ✅ Restart after manual MCP stop

---

## 🛣️ Roadmap

### v1.2.0 - OpenClaw Support

**Planned Features:**
- [ ] **OpenClaw Agent Integration** - Add OpenClaw as supported AI agent
- [ ] **Scheduler** - Automated task scheduling for AI agents
- [ ] **Security Policy Engine** - Fine-grained access control and policies
- [ ] **Multi-Agent Support** - Simultaneous OpenCode + OpenClaw instances

**Why OpenClaw?**

OpenClaw provides additional capabilities that complement OpenCode:
- Different coding paradigms
- Specialized agents for specific tasks
- Alternative when OpenCode is unavailable

**Challenges to Address:**

1. **Scheduler Implementation**
   - When to run which agent?
   - Task prioritization
   - Resource allocation
   - Cost optimization

2. **Security Policy Engine**
   - Access control per project
   - Data governance policies
   - Compliance enforcement (GDPR, HIPAA, etc.)
   - Audit logging

### Future Vision

```
MoJoAssistant Core
    ↓
Agent Orchestrator (v1.2+)
    ├─→ OpenCode Manager
    │   ├─→ OpenCode Instance 1
    │   ├─→ OpenCode Instance 2
    │   └─→ OpenCode Instance 3
    │
    └─→ OpenClaw Manager (v1.2+)
        ├─→ OpenClaw Instance 1
        ├─→ OpenClaw Instance 2
        └─→ OpenClaw Instance 3

Shared:
    ├─→ Global Scheduler
    ├─→ Security Policy Engine
    └─→ Unified MCP Interface
```

---

## 🔄 Migration from v1.0

### What Changed?

- **Old**: Per-project `opencode-mcp-tool` instances (1:1 architecture)
- **New**: Single global `opencode-mcp-tool` (N:1 architecture)

### Migration Steps

**1. Stop all existing projects:**
```bash
opencode_stop project-name
```

**2. Create global configuration:**
```bash
cp app/mcp/opencode/templates/opencode-manager.env.template ~/.memory/opencode-manager.env
chmod 600 ~/.memory/opencode-manager.env
```

**3. Update configuration:**
```bash
nano ~/.memory/opencode-manager.env
# Add your OPENCODE_MCP_TOOL_PATH and OPENCODE_BIN paths
```

**4. Restart projects:**
```bash
opencode_restart project-name
```

See `GLOBAL_CONFIG_MIGRATION.md` for detailed instructions.

---

## 💡 Use Cases

### 1. Individual Developer

**Scenario:** Multiple projects need AI coding assistance.

**Solution:**
```bash
# Start OpenCode agents for each project
opencode_start blog-api git@github.com:user/blog.git
opencode_start mobile-app git@github.com:user/mobile.git

# Work on projects with AI assistance
# All managed through unified MCP interface
```

### 2. Small Team

**Scenario:** Team members need AI assistance on different codebases.

**Solution:**
```bash
# Developer 1: Start their project
opencode_start backend-api git@github.com:company/backend.git

# Developer 2: Start their project
opencode_start mobile-app git@github.com:company/mobile.git

# Developer 3: Start their project
opencode_start web-frontend git@github.com:company/web.git

# All running locally, unified management
```

### 3. Continuous Integration

**Scenario:** AI agents need to run in CI/CD pipeline.

**Solution:**
```bash
# CI Script:
opencode_start project-$BUILD_ID $REPO_URL
# Run tests with AI assistance
opencode_stop project-$BUILD_ID

# Project isolation prevents conflicts
```

---

## 🎓 Key Takeaways

### What v1.1.0 Provides

1. **Agent Orchestration Layer** - Manages external AI agents (OpenCode)
2. **Multi-Project Support** - Run multiple AI agent instances
3. **Unified MCP Interface** - Single port (3005) for all agents
4. **Production-Ready** - Health monitoring, state persistence, auto-recovery
5. **Future-Proof** - Architecture ready for OpenClaw and other agents

### What's Coming Next

1. **OpenClaw Integration** (v1.2.0)
   - Support for OpenClaw AI agent
   - Scheduler for task routing
   - Security policy engine

2. **Multi-Agent Support** (v1.2.0+)
   - Simultaneous OpenCode + OpenClaw
   - Intelligent task routing
   - Resource optimization

---

## 📞 Support

- **Issues**: https://github.com/AvengerMoJo/MoJoAssistant/issues
- **Discussions**: https://github.com/AvengerMoJo/MoJoAssistant/discussions
- **Documentation**: https://github.com/AvengerMoJo/MoJoAssistant/tree/main/app/mcp/opencode

---

## 📄 License

MIT License - See LICENSE file for details

---

## 🙏 Acknowledgments

- **OpenCode team** - Amazing AI coding agent
- **opencode-mcp-tool contributors** - MCP protocol implementation
- **MCP (Model Context Protocol) community** - Open protocol
- **All contributors** - Made v1.1.0 possible

---

**MoJoAssistant v1.1.0 - Extending AI Agent Capabilities**

*Orchestrate multiple AI agents. Prepare for OpenClaw. Build the future.*
