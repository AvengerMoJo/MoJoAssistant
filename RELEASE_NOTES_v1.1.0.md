# MoJoAssistant v1.1.0 Release Notes

**Release Date**: February 9, 2026
**Tag**: v1.1.0
**Status**: Production Ready

---

## 🚀 The Data Protection Imperative

### Why MoJoAssistant with OpenCode Manager Matters

**Everyone is using auto-agent tools like OpenClaw** - but at what cost?

These agents often:
- ❌ Send your code to external servers without clear consent
- ❌ Store your private repositories in third-party cloud infrastructure
- ❌ Lack transparency about where your data goes
- ❌ Offer no control over data retention or deletion
- ❌ Expose your intellectual property to potential security risks

**MoJoAssistant v1.1.0 changes the game.**

### 🛡️ Your Data, Your Control

MoJoAssistant with OpenCode Manager provides **enterprise-grade data protection** for your AI coding workflow:

| Feature | Auto-Agent Tools | MoJoAssistant v1.1.0 |
|----------|-----------------|----------------------|
| **Data Storage** | Third-party cloud | **Local-only by default** |
| **Code Processing** | Remote servers | **Your own machines** |
| **SSH Keys** | Managed by others | **Generated locally, never shared** |
| **Git Access** | Through their infrastructure | **Direct access via your keys** |
| **Data Retention** | Unknown/black-box | **Full transparency and control** |
| **Security** | Trust us | **Open source, auditable** |

---

## 🎯 What's New in v1.1.0

### OpenCode Manager - Production-Ready AI Agent Orchestration

**The first privacy-first AI coding agent system** that keeps your data on your infrastructure.

#### Core Capabilities

**1. Multi-Project Management**
```bash
# Run multiple AI coding projects simultaneously
opencode_start blog-api git@github.com:user/blog-api.git
opencode_start mobile-app git@github.com:user/mobile-app.git
opencode_start backend-service git@github.com:user/backend.git

# All managed through your own infrastructure
```

**2. N:1 Architecture - Efficient and Secure**
```
Your Local Environment:
┌─────────────────────────────────────────────────────────────┐
│  OpenCode Instance 1 (port 4100)                    │
│  OpenCode Instance 2 (port 4101)                      │
│  OpenCode Instance 3 (port 4102)                      │
│         ↓                                            │
│  Global MCP Tool (port 3005)                          │
│  - Routes to all instances                              │
│  - Single point of control                              │
│  - Locally hosted                                       │
│         ↓                                            │
│  Your AI Clients (Claude Desktop, etc.)                │
└─────────────────────────────────────────────────────────────┘

❌ No external data transmission
✅ No third-party infrastructure
✅ Full data sovereignty
```

**3. Enterprise Security Features**

**SSH Key Management:**
- ✅ Per-project SSH keys generated locally
- ✅ Keys never leave your environment
- ✅ Automatic generation with `ssh-keygen`
- ✅ Full control over key rotation and deletion

**Configuration Security:**
- ✅ Password-protected OpenCode instances
- ✅ Bearer token authentication for MCP tool
- ✅ File permissions enforced (0600 for secrets)
- ✅ No hardcoded credentials in codebase

**Network Security:**
- ✅ Bind to specific interfaces (0.0.0.0 for remote access, localhost for local)
- ✅ Password authentication required for all connections
- ✅ Support for cloudflared tunnels (no open ports)

**4. State Persistence & Recovery**
```bash
# Your AI agents survive system restarts
sudo reboot

# Projects automatically resume
opencode_status blog-api
# → Running (auto-recovered from persistent state)
```

**5. Health Monitoring & Auto-Recovery**
- ✅ Automatic health checks for OpenCode instances
- ✅ Automatic health checks for MCP tool
- ✅ Auto-restart on failure
- ✅ Detailed logging for troubleshooting

**6. Process Lifecycle Management**

```bash
# Start - Bootstrap new project
opencode_start my-project git@github.com:user/repo.git
# → Clones repo
# → Generates SSH key
# → Starts OpenCode server
# → Adds to global config
# → Starts MCP tool if needed

# Status - Check health and running state
opencode_status my-project
# → Shows OpenCode status
# → Shows MCP tool status
# → Shows PID, ports, health

# Restart - Reuse ports and config
opencode_restart my-project
# → Stops OpenCode gracefully
# → Restarts with same port
# → Preserves all settings

# Stop - Clean shutdown
opencode_stop my-project
# → Stops OpenCode
# → Updates config to inactive
# → Auto-stops MCP tool if no projects left
```

---

## 🔒 Privacy & Security Guarantees

### What We Don't Do

❌ We don't send your code to external servers
❌ We don't store your private SSH keys
❌ We don't require cloud infrastructure
❌ We don't collect telemetry by default
❌ We don't lock your data in proprietary formats

### What We Do

✅ **Local-First Architecture**: All processing happens on your machines
✅ **Transparent Data Flow**: You can see exactly where your data goes
✅ **Open Source**: Full codebase visibility - audit anytime
✅ **You Own Your Data**: Delete anytime, export anytime
✅ **Enterprise-Grade Security**: Password protection, SSH key isolation, secure authentication
✅ **Compliance Ready**: Suitable for regulated industries (healthcare, finance, government)

---

## 📊 Comparison: MoJoAssistant vs Auto-Agent Tools

| Aspect | Auto-Agent (OpenClaw, etc.) | MoJoAssistant v1.1.0 |
|---------|-------------------------------|--------------------------|
| **Data Location** | Cloud (unknown region) | Your infrastructure |
| **SSH Key Access** | They hold your keys | You hold your keys |
| **Git Operations** | Through their servers | Direct via SSH |
| **Code Privacy** | Unclear, terms vary | 100% private by design |
| **Transparency** | Black-box operation | Fully auditable open source |
| **Data Export** | Maybe | Always, full control |
| **Data Deletion** | Request-based | Immediate, you control it |
| **Compliance** | Questionable | Ready for enterprise |
| **Cost** | Subscription-based | Self-hosted, free software |
| **Multi-Project** | Limited | Unlimited, local control |

---

## 🎓 Use Cases

### 1. Individual Developers

**Before (Auto-Agent):**
- Sign up for SaaS service
- Give them access to your GitHub
- Hope they don't store your code
- Pay monthly subscription
- Data leaves your control

**After (MoJoAssistant v1.1.0):**
```bash
# 5 minutes setup, no signup
opencode_start my-project git@github.com:user/repo.git

# Your code never leaves your infrastructure
# You control everything
# No subscription fees
# Enterprise-grade security
```

### 2. Small Teams

**Challenge**: Multiple developers need AI coding assistance, but can't share sensitive code externally.

**Solution with MoJoAssistant:**
```bash
# Developer 1: Start their project
opencode_start backend-api git@github.com:company/backend.git

# Developer 2: Start their project  
opencode_start mobile-app git@github.com:company/mobile.git

# Developer 3: Start their project
opencode_start web-frontend git@github.com:company/web.git

# All running locally, all data stays in company infrastructure
# No external data exposure
# Full compliance with data governance policies
```

### 3. Enterprise / Regulated Industries

**Requirement**: AI coding assistance for healthcare, finance, or government projects with strict data governance.

**MoJoAssistant provides:**
- ✅ **Data Sovereignty**: Never leaves approved infrastructure
- ✅ **Audit Trail**: Full logging of all operations
- ✅ **Access Control**: Password-protected, SSH key isolation
- ✅ **Compliance**: Meets HIPAA, GDPR, SOX requirements (when configured correctly)
- ✅ **No Third-Party Risk**: Open source, self-hosted, auditable

---

## 🚦 Quick Start (5 Minutes)

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
# Paths (update to your actual locations)
OPENCODE_MCP_TOOL_PATH=/home/user/Development/Sandbox/opencode-mcp-tool
OPENCODE_BIN=/home/user/.bun/install/global/node_modules/opencode-linux-x64/bin/opencode

# Passwords (use strong, unique passwords)
OPENCODE_SERVER_PASSWORD=your-strong-password-here
GLOBAL_MCP_BEARER_TOKEN=your-bearer-token-here

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

# Expected output:
{
  "status": "ok",
  "project": "my-project",
  "opencode": {
    "pid": 12345,
    "port": 4100,
    "status": "running",
    "running": true
  },
  "global_mcp_tool": {
    "pid": 12346,
    "port": 3005,
    "status": "running",
    "running": true,
    "active_projects": 1
  }
}
```

---

## 📚 Available Tools

| Tool | Description | Example |
|------|-------------|----------|
| `opencode_start` | Bootstrap new OpenCode project | `opencode_start blog-api git@github.com:user/blog.git` |
| `opencode_stop` | Stop OpenCode project | `opencode_stop blog-api` |
| `opencode_restart` | Restart OpenCode project | `opencode_restart blog-api` |
| `opencode_status` | Get project status | `opencode_status blog-api` |
| `opencode_list` | List all projects | `opencode_list` |
| `opencode_mcp_restart` | Restart global MCP tool | `opencode_mcp_restart` |
| `opencode_mcp_status` | Get MCP tool status | `opencode_mcp_status` |
| `opencode_llm_config` | Get/set LLM configuration | `opencode_llm_config` |

---

## 🏗️ Architecture Deep Dive

### N:1 Architecture Explained

**Why N:1?**

Traditional approach (1:1):
```
Project 1 → MCP Tool 1 (port 5100)
Project 2 → MCP Tool 2 (port 5101)
Project 3 → MCP Tool 3 (port 5102)
```

**Problems:**
- Port conflicts
- Resource waste
- Hard to manage
- No unified control

**MoJoAssistant N:1:**
```
Project 1 ─┐
Project 2 ─┼→ Global MCP Tool (port 3005) → AI Clients
Project 3 ─┘
```

**Benefits:**
- ✅ Single port (3005) for all projects
- ✅ Unified configuration
- ✅ Efficient resource usage
- ✅ Centralized control
- ✅ Server config file (`opencode-mcp-tool-servers.json`)
- ✅ Dynamic server selection

### Server Configuration

**Location**: `~/.memory/opencode-mcp-tool-servers.json`

**Example:**
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

**Security:**
- ✅ File permissions: 0600 (owner read/write only)
- ✅ Auto-generated per project
- ✅ Hot-reload supported (opencode-mcp-tool watches file)
- ✅ No hardcoded passwords in codebase

---

## 🔧 Advanced Configuration

### Environment Variables

```env
# MCP Tool Configuration
GLOBAL_MCP_BEARER_TOKEN=your-secure-token
GLOBAL_MCP_TOOL_PORT=3005
OPENCODE_MCP_TOOL_PATH=/path/to/opencode-mcp-tool

# OpenCode Configuration
OPENCODE_SERVER_PASSWORD=your-password
OPENCODE_BIN=/path/to/opencode
OPENCODE_SERVER_HOSTNAME=0.0.0.0

# Development Mode
ENVIRONMENT=development
LOG_LEVEL=INFO
```

### Port Management

**Automatic Port Allocation:**
- OpenCode servers: 4100-4199 (auto-assign)
- MCP tool: 3005 (configurable)

**Port Reuse:**
- Restart operations preserve ports
- Prevents connection issues for clients

### Network Configuration

**Local Access Only:**
```env
OPENCODE_SERVER_HOSTNAME=127.0.0.1
```

**Remote Access (Password Protected):**
```env
OPENCODE_SERVER_HOSTNAME=0.0.0.0
```

**Cloudflared Tunnel (No Open Ports):**
```bash
# Use cloudflared to expose without opening ports
cloudflared tunnel --url http://127.0.0.1:4100
```

---

## 🐛 Bug Fixes in v1.1.0

| Issue | Impact | Fix |
|-------|---------|------|
| `active_project_count` not incrementing | Global MCP tool wouldn't start after all projects stopped | Added logic to increment count when restarting stopped projects |
| Built-in models missing in LLM config | Can't use OpenCode built-in providers | Query `opencode models` CLI to get all models |
| Redundant OpenCode tools | Confusing tool names | Consolidated to essential tools |
| Hot reload broken | Development workflow interrupted | Fixed with watchfiles alternative |
| PID tracking issues | Stale processes not detected | Improved process lifecycle management |

---

## 📖 Documentation

**Complete documentation available in `app/mcp/opencode/`:**

- `README.md` - Comprehensive feature documentation
- `ARCHITECTURE_N_TO_1.md` - N:1 architecture deep dive
- `CONFIGURATION.md` - Setup and configuration guide
- `GLOBAL_CONFIG_MIGRATION.md` - Migration from v1.0
- `SSH_KEY_ARCHITECTURE.md` - SSH key management
- `SECURITY_AUDIT_RESULTS.md` - Security review
- `TEST_RESULTS_v1.1_BETA.md` - Test results
- `SETUP_GLOBAL_CONFIG.md` - Step-by-step setup

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

## 🎓 Migration from v1.0

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

## 🚀 What's Next

### Roadmap

- [ ] Web UI for project management
- [ ] Auto-scaling based on project load
- [ ] Integration with cloud providers (AWS, GCP, Azure)
- [ ] Backup and disaster recovery
- [ ] Team collaboration features
- [ ] Performance monitoring and analytics
- [ ] Integration with CI/CD pipelines

---

## 💡 Why Choose MoJoAssistant?

**When everyone is racing to send your data to the cloud, MoJoAssistant does the opposite.**

We believe:
- Your code should stay on your infrastructure
- You should have full transparency about data flow
- Security through obscurity is not security
- Open source is better than proprietary black-boxes
- Privacy is a right, not a premium feature

**v1.1.0 is our commitment to that vision.**

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

- OpenCode team for the amazing AI coding agent
- opencode-mcp-tool contributors
- The MCP (Model Context Protocol) community
- All contributors who made v1.1.0 possible

---

**MoJoAssistant v1.1.0 - Your Data, Your Control.**

*Protect your intellectual property. Choose privacy by design.*
