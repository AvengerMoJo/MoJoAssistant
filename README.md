# MoJoAssistant

**Personal AI memory, scheduling, and agent orchestration — local-first, privacy-preserving.**

MoJoAssistant sits between you and your AI systems. It keeps your memory, context, and
workflow state on your own machine, then exposes everything through a clean 14-tool MCP
surface that any MCP-capable client (Claude Desktop, Claude Code, etc.) can use directly.

Current release: `v1.2.16-beta`

---

## What It Does

| Layer | What you get |
|-------|-------------|
| **Memory** | Persistent conversation + document memory with semantic search; role-scoped knowledge isolation |
| **MCP Server** | 14 hub tools for any MCP client — Claude Desktop, Claude Code, custom agents |
| **Scheduler** | Cron + one-shot task runner with role-based agentic execution; HITL pause/resume |
| **Roles** | Named AI personas with dynamic system prompts, tool access, data boundaries, and two-tier knowledge growth |
| **Policy** | Inline safety checker — blocks credential access, reverse shells, exfiltration; per-task `danger_budget` override |
| **Dashboard** | Browser UI at `/dashboard` — event log, tasks (incl. cron history), role chat, policy violations |
| **Dreaming** | Nightly memory consolidation: raw sessions → ABCD semantic archives → searchable knowledge base |
| **External MCP** | Plug in external MCP servers (tmux terminal, Playwright browser) via `config/mcp_servers.json` |
| **Google Workspace** | Calendar, Drive, Gmail via `external_agent` hub |
| **Notifications** | ntfy / FCM push, SSE stream, persistent event log |
| **Benchmarks** | LOCOMO, LongMemEval, ABCD e2e, role memory evaluation harness |

---

## Quick Start

### 1. Clone with submodules

```bash
git clone --recurse-submodules https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant
```

### 2. Run the installer

**Linux / macOS:**
```bash
./scripts/install.sh
```

**Windows:**
```bat
scripts\install.bat
```

The installer creates a venv, installs dependencies, runs a preflight check for
required system tools (tmux, node, cargo), and creates startup scripts.

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env — set API keys, LLM endpoint, MEMORY_PATH if needed
```

### 4. Start the server

```bash
# MCP over stdio (Claude Desktop)
python unified_mcp_server.py --mode stdio

# HTTP + MCP (dashboard, REST, scheduler daemon)
python unified_mcp_server.py --mode http --port 8000

# Docker
docker compose -f docker/docker-compose.yml up mojoassistant
```

### Run as a persistent service (optional)

**Linux (systemd user service):**
```bash
./scripts/install_service.sh          # install + start
./scripts/install_service.sh --stop   # stop + remove
./scripts/install_service.sh --status # status + logs
```

**macOS (launchd user agent):**
```bash
./scripts/install_service_macos.sh          # install + start
./scripts/install_service_macos.sh --stop   # stop + remove
./scripts/install_service_macos.sh --status # status + logs
```

Both service scripts auto-update the Claude MCP config to HTTP mode.

See [Installation Guide](docs/installation/INSTALL.md) and [Quick Start](docs/installation/QUICKSTART.md) for full setup.

---

## The 14 MCP Tools

All functionality is exposed through hub tools. Each hub dispatches to sub-actions.

| Tool | What it covers |
|------|---------------|
| `get_context` | Orientation, attention inbox, recent events, task session log |
| `search_memory` | Semantic search across conversations and documents |
| `add_conversation` | Store a conversation turn; `scope="framework"` writes to shared cross-role store |
| `reply_to_task` | Send a HITL reply to a waiting agentic task |
| `memory` | Conversation management, document ingestion, stats |
| `knowledge` | Code/doc repo indexing and file retrieval |
| `config` | Runtime configuration, LLM resources, roles, system health (`doctor`, `doctor_improve`) |
| `scheduler` | Task lifecycle — add, list, get, remove, daemon control |
| `dream` | Memory consolidation pipeline — process, list, upgrade |
| `role` | Role CRUD — create, update, list, get role definitions |
| `agent` | Coding agent lifecycle (Claude Code, OpenCode) |
| `external_agent` | Google Workspace gateway (Calendar, Drive, Gmail) |
| `task_session_read` | Read the full message transcript for a completed task session |
| `task_report_read` | Read the structured result report for a completed task |

### Example usage in Claude Desktop

```
Use the scheduler tool to add a daily research task for researcher at 9am.
Use the config tool to check what LLM resources are available.
Use the dream tool to list recent memory archives.
```

---

## Roles and Agentic Tasks

Roles are named AI personas stored in `~/.memory/roles/{role_id}.json`.
Each role has its own system prompt (generated dynamically from role fields),
tool access list, resource tier preference, and optional data boundary policy.

```json
{
  "name": "Researcher",
  "persona": "Research analyst focused on AI and distributed systems",
  "capabilities": ["web_search", "memory_search", "memory_write"],
  "local_only": false,
  "schedule_cron": "0 9 * * 1-5"
}
```

Add a task via MCP:

```json
{
  "tool": "scheduler",
  "args": {
    "action": "add",
    "type": "assistant",
    "role_id": "researcher",
    "description": "Research the latest papers on KV cache compression"
  }
}
```

Roles can dispatch sub-tasks (`dispatch_subtask`) with automatic depth limiting to
prevent delegation loops.

When an agent runs out of iterations without finishing, it surfaces a HITL question
instead of silently failing — reply "yes" to grant more cycles, "no" to close it out.

### Two-Tier Role Knowledge

Roles learn in two layers:

- **Role-private** (`scope="role"`, default) — knowledge stays inside that role's store
- **Framework-shared** (`scope="framework"`) — patterns written here are visible to every role at task start

The executor auto-detects workflow problems (empty response loops, repeated rejection patterns) and writes a framework entry with diagnosis and mitigation hints — roles learn from each other's failures without manual curation.

---

## Policy and Safety

Every tool call in an agentic task passes through an inline policy pipeline before
execution. No tool call is made if a checker blocks it.

```json
"policy": {
  "checkers": ["static", "content", "data_boundary", "context"],
  "denied_tools": ["bash_exec"],
  "danger_budget": 3
}
```

`local_only: true` is a one-liner shorthand that locks a role to free-tier local
resources and blocks all external MCP calls.

Tasks can set `danger_budget` in config to override the role default for a single
run — useful for high-privilege provisioning without permanently raising the role's budget.

**Content patterns** cover:
- Secrets and credentials (API keys, SSH keys, `.aws/credentials`, `.netrc`)
- C2 / reverse shells (`/dev/tcp/`, `nc -e /bin/sh`, socat, mkfifo)
- Data exfiltration (`curl --data` to external URLs, `scp`, `rsync` outbound)
- Privilege escalation (`chmod` SUID, `crontab -e`, `LD_PRELOAD`)

The **Security Sentinel** (`~/.memory/roles/security_sentinel.json`) runs nightly at
03:00, audits the EventLog, and writes a digest to memory — fully local, no external
calls.

---

## Memory Path

All persistent state lives under `MEMORY_PATH` (default: `~/.memory`).
Set it in `.env` to redirect everything to a project-local directory:

```bash
MEMORY_PATH=/path/to/your/memory
```

Substructure:

```
$MEMORY_PATH/
  conversations_multi_model.json   — conversation store
  scheduler_tasks.json             — task queue
  task_sessions/                   — agentic session logs
  roles/                           — role definitions + chat history
  dreams/                          — dreaming archives
  config/                          — personal config overlays
  events.json                      — event log
```

---

## Dashboard

Available at `http://localhost:{port}/dashboard` on any running instance.

- Live event log (SSE auto-update)
- Scheduler task list with status, iteration logs, and session transcript
- **Cron task history** — recurring tasks show last-run time and next-run countdown even while pending
- **Role Chat** — persistent conversation UI for any role (`/dashboard/chat`)
- Policy violation log

Protected by the dashboard password set in `.env`.

---

## LLM Resources

MoJoAssistant routes LLM calls through a resource pool:

- **Local** — LM Studio or any OpenAI-compatible server
- **Free API** — OpenRouter free-tier with multi-account rotation and dynamic model detection
- **API** — OpenRouter paid, OpenAI, Anthropic, Google

Configure via the `config` MCP tool at runtime — no server restart needed:

```
Use the config tool to show available LLM resources.
Use the config tool to approve the new lmstudio resource.
```

`agentic_capable` is tested per-resource via a smoke test (tool call → write_file → disk verify).
Results are cached for 7 days and expire automatically — a recovered model isn't blocked indefinitely.

`config(action="doctor_improve")` analyses running system health and proposes concrete config fixes
for unreachable resources, stale capability flags, and missing role tools.

## External MCP Servers

MoJoAssistant can spawn or connect to external MCP servers alongside its own tools.
Configure them in `config/mcp_servers.json` (system defaults) or
`~/.memory/config/mcp_servers.json` (personal overrides):

```json
{
  "servers": [
    {
      "id": "tmux",
      "name": "tmux MCP",
      "transport": "stdio",
      "command": "~/.cargo/bin/tmux-mcp-rs",
      "args": ["--shell-type", "bash", "--config", "config/tmux-mcp.toml"],
      "category": "terminal",
      "enabled": true
    }
  ]
}
```

Two transport modes: `stdio` (MoJo spawns the process) and `http` (connect to a running server).
The preflight checker validates required binaries (`tmux`, `node`, `cargo`) before install.

---

## Documentation

### Getting Started
- [Installation Guide](docs/installation/INSTALL.md)
- [Quick Start](docs/installation/QUICKSTART.md)
- [MCP Client Setup](docs/configuration/MCP_CLIENT_SETUP.md)
- [MCP Smoke Checklist](docs/guides/MCP_SMOKE_CHECKLIST.md)

### Configuration
- [Resource Pool Onboarding](docs/guides/RESOURCE_POOL_ACCOUNT_ONBOARDING.md)
- [Notifications Setup](docs/guides/NOTIFICATIONS_SETUP.md)
- [Google Workspace Setup](docs/guides/GOOGLE_WORKSPACE_SETUP.md)

### Architecture
- [System Overview](docs/architecture/SYSTEM_README.md)
- [Scheduler Architecture](docs/architecture/SCHEDULER_ARCHITECTURE.md)
- [MCP Design](docs/architecture/MCP_DESIGN.md)
- [Sub-Agent Dispatch](docs/architecture/SUB_AGENT_DISPATCH.md)
- [Role Chat Interface](docs/architecture/ROLE_CHAT_INTERFACE.md)
- [Dreaming Specification](docs/architecture/DREAMING_SPECIFICATION.md)
- [Security Behavioral Monitor](docs/architecture/SECURITY_BEHAVIORAL_MONITOR.md)

### Releases
- [v1.2.16-beta Release Notes](docs/releases/RELEASE_NOTES_v1.2.16-beta.md)
- [v1.2.14-beta Release Notes](docs/releases/RELEASE_NOTES_v1.2.14-beta.md)
- [v1.2.8-beta Release Notes](docs/releases/RELEASE_NOTES_v1.2.8-beta.md)
- [Roadmap](docs/releases/ROADMAP_future.md)
- [All Releases](docs/releases/)

---

## Docker

```bash
# CPU
docker compose -f docker/docker-compose.yml up mojoassistant

# AMD ROCm GPU
docker compose -f docker/docker-compose.yml up mojoassistant-rocm
```

HuggingFace model cache is mounted from the host — no re-download on rebuild.
Health check: `GET /health`.

---

## CI / CD

GitHub Actions on every push:
- **Smoke test** — starts the server, polls `/health`, asserts `status=healthy`
- **Docker build** — CPU image build to catch Dockerfile regressions
- **Docker publish** — pushes to `ghcr.io` on `main` and version tags

---

## Development

Agent and coding policy:
- [`AGENTS.md`](AGENTS.md)
- [`Coding Agents Rules.md`](Coding%20Agents%20Rules.md)

Before merging:
- run `pytest tests/` — 568 tests collected
- run [MCP Smoke Checklist](docs/guides/MCP_SMOKE_CHECKLIST.md) for live MCP validation

---

## Status

Active beta (`v1.2.16`). Core memory, MCP, scheduler, policy, role chat, and dreaming
pipeline are production-ready for personal use. External MCP servers (tmux terminal,
Playwright browser), Google Workspace, and coding agent integrations require additional
setup. See the roadmap for what's next.
