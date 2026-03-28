# MoJoAssistant

**Personal AI memory, scheduling, and agent orchestration — local-first, privacy-preserving.**

MoJoAssistant sits between you and your AI systems. It keeps your memory, context, and
workflow state on your own machine, then exposes everything through a clean 12-tool MCP
surface that any MCP-capable client (Claude Desktop, Claude Code, etc.) can use directly.

Current release: `v1.2.7-beta`

---

## What It Does

| Layer | What you get |
|-------|-------------|
| **Memory** | Persistent conversation + document memory with semantic search |
| **MCP Server** | 12 hub tools for any MCP client — Claude Desktop, Claude Code, custom agents |
| **Scheduler** | Cron + one-shot task runner with role-based agentic execution |
| **Roles** | Named AI personas with custom prompts, tool access, and data boundary policy |
| **Policy** | Inline safety checker — blocks credential access, reverse shells, exfiltration |
| **Dashboard** | Browser UI at `/dashboard` — event log, tasks, role chat, policy violations |
| **Dreaming** | Nightly memory consolidation: raw conversations → semantic archives |
| **Google Workspace** | Calendar, Drive, Gmail via `external_agent` hub |
| **Notifications** | ntfy / FCM push, SSE stream, persistent event log |

---

## Quick Start

### 1. Clone with submodules

```bash
git clone --recurse-submodules https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant
```

### 2. Install dependencies

```bash
pip install -r requirements-runtime.txt
pip install submodules/dreaming-memory-pipeline/
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env — set API_KEY, LLM endpoint, MEMORY_PATH if needed
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

See [Installation Guide](docs/installation/INSTALL.md) and [Quick Start](docs/installation/QUICKSTART.md) for full setup.

---

## The 12 MCP Tools

All functionality is exposed through hub tools. Each hub dispatches to sub-actions.

| Tool | What it covers |
|------|---------------|
| `get_context` | Orientation, attention inbox, recent events, task session log |
| `search_memory` | Semantic search across conversations and documents |
| `add_conversation` | Store a conversation turn in memory |
| `reply_to_task` | Send a HITL reply to a waiting agentic task |
| `web_search` | Google search (requires API key) |
| `memory` | Conversation management, document ingestion, stats |
| `knowledge` | Code/doc repo indexing and file retrieval |
| `config` | Runtime configuration, LLM resources, roles, system health |
| `scheduler` | Task lifecycle — add, list, get, remove, daemon control |
| `dream` | Memory consolidation pipeline — process, list, upgrade |
| `agent` | Coding agent lifecycle (Claude Code, OpenCode) |
| `external_agent` | Google Workspace gateway (Calendar, Drive, Gmail) |

### Example usage in Claude Desktop

```
Use the scheduler tool to add a daily research task for Rebecca at 9am.
Use the config tool to check what LLM resources are available.
Use the dream tool to list recent memory archives.
```

---

## Roles and Agentic Tasks

Roles are named AI personas stored in `~/.memory/roles/{role_id}.json`.
Each role has its own system prompt, tool access list, resource tier preference,
and optional data boundary policy.

```json
{
  "name": "Rebecca",
  "system_prompt": "You are Rebecca, a research analyst...",
  "tool_access": ["web_search", "memory_search", "memory_write"],
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
    "role_id": "rebecca",
    "description": "Research the latest papers on KV cache compression"
  }
}
```

Roles can dispatch sub-tasks (`dispatch_subtask`) with automatic depth limiting to
prevent delegation loops.

When an agent runs out of iterations without finishing, it surfaces a HITL question
instead of silently failing — reply "yes" to grant more cycles, "no" to close it out.

---

## Policy and Safety

Every tool call in an agentic task passes through an inline policy pipeline before
execution. No tool call is made if a checker blocks it.

```json
"policy": {
  "checkers": ["static", "content", "data_boundary", "context"],
  "denied_tools": ["bash_exec"]
}
```

`local_only: true` is a one-liner shorthand that locks a role to free-tier local
resources and blocks all external MCP calls.

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
- Scheduler task list with status and iteration logs
- **Role Chat** — persistent conversation UI for any role (`/dashboard/chat`)
- Policy violation log

Protected by the same API key as the MCP endpoint.

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
- [v1.2.7-beta Release Notes](docs/releases/RELEASE_NOTES_v1.2.7-beta.md)
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
- run `pytest tests/` — 342 tests, 2 skipped expected
- run [MCP Smoke Checklist](docs/guides/MCP_SMOKE_CHECKLIST.md) for live MCP validation

---

## Status

Active beta. Core memory, MCP, scheduler, policy, and role chat are production-ready
for personal use. Some integrations (Google Workspace, coding agent) require additional
external setup. See the roadmap for what's next.
