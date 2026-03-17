# MoJoAssistant

MoJoAssistant is a personal AI memory and workflow system.

It combines:
- persistent memory and knowledge retrieval
- an MCP server for AI clients
- local and API-backed LLM routing
- scheduler and agentic task execution
- optional coding-agent management

Current release: `v1.1.9-beta`

## What It Is

MoJoAssistant is designed to sit between you and AI systems.
It keeps your memory, context, and workflow state local, then exposes that through CLI, MCP, and scheduler-driven automation.

Core capabilities:
- memory search across conversations and documents
- MCP tools for assistants and clients
- scheduler tasks for automation and background work
- agentic execution with resource policy and review workflow
- Google Workspace integration through `google_service`
- optional OpenCode-based coding agent management

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

### 3. Start the server

MCP + HTTP server (recommended):

```bash
python unified_mcp_server.py --mode http --port 8000
```

Or via Docker:

```bash
docker compose -f docker/docker-compose.yml up mojoassistant
```

See [Quick Start](docs/claude-guide/QUICKSTART.md) for full setup including `.env` configuration.

## Main Entry Points

### Interactive CLI
Use this first if you want to explore the system directly.

```bash
python app/interactive-cli.py
```

### MCP Server
Use this for Claude Desktop or other MCP-capable clients.

```bash
python unified_mcp_server.py --mode stdio
```

HTTP mode:

```bash
python unified_mcp_server.py --mode http --port 8000
```

### Scheduler and Agentic Tasks
Use MCP tools such as:
- `scheduler_add_task` — queue a task (immediate, scheduled, or cron)
- `scheduler_get_task` / `scheduler_list_tasks` — monitor progress
- `task_session_read` — read the full LLM conversation log for a task
- `resource_pool_status` / `resource_pool_approve` — manage LLM resources
- `get_recent_events` — poll the persistent event log

### Google Workspace
Google Calendar and related integrations require external setup first.
MoJoAssistant delegates these operations through the `gws` CLI.

Start here:
- [Google Workspace Setup](docs/guides/GOOGLE_WORKSPACE_SETUP.md)
- [Google Calendar Scheduler Policy](docs/guides/GOOGLE_CALENDAR_SCHEDULER_POLICY.md)

## Documentation Map

### Start Here
- [Quick Start](docs/installation/QUICKSTART.md)
- [Installation Guide](docs/installation/INSTALL.md)
- [User Guide](docs/guides/user-guide.md)

### MCP and Client Setup
- [MCP Client Setup](docs/configuration/MCP_CLIENT_SETUP.md)
- [MCP Smoke Checklist](docs/guides/MCP_SMOKE_CHECKLIST.md)

### Scheduler, Resource Pool, and Google Workspace
- [Google Workspace Setup](docs/guides/GOOGLE_WORKSPACE_SETUP.md)
- [Google Calendar Scheduler Policy](docs/guides/GOOGLE_CALENDAR_SCHEDULER_POLICY.md)
- [Resource Pool Account Onboarding](docs/guides/RESOURCE_POOL_ACCOUNT_ONBOARDING.md)

### Notifications
- [Notifications Setup Guide](docs/guides/NOTIFICATIONS_SETUP.md)

### Architecture and Design
- [System Overview](docs/architecture/SYSTEM_README.md)
- [Scheduler Architecture](docs/architecture/SCHEDULER_ARCHITECTURE.md)
- [Dreaming Specification](docs/architecture/DREAMING_SPECIFICATION.md)

### Releases
- [v1.1.9-beta Release Notes](docs/releases/RELEASE_NOTES_v1.1.9-beta.md)
- [Previous Releases](docs/releases)

### Optional OpenCode Integration
- [OpenCode Manager README](app/mcp/opencode/README.md)

## Feature Areas

### Memory
- conversation memory
- knowledge/document ingestion
- semantic retrieval across memory tiers

### MCP
- memory tools
- scheduler tools
- agent manager tools
- Google Workspace gateway

### Scheduler and Agentic Execution
- scheduled tasks (one-time or cron)
- `assistant` tasks — role-based LLM think-act loops (Ahman and others)
- `dreaming` tasks — nightly memory consolidation
- `normal`, `deep_research`, and `parallel_discovery` execution modes
- sandbox safety policy with read/write separation
- persistent event log with `get_recent_events` polling

### Notifications
- persistent event log — all events survive server restarts (500-event circular buffer)
- SSE stream `GET /events/tasks` — real-time for browser/WebSocket clients
- `get_recent_events` MCP tool — polling for Claude Desktop and MCP clients
- independent push adapters — ntfy, FCM, and others; each has its own cursor and filter
- config-driven: enable/disable/add channels via `notifications_config.json`, no code change

### Docker
- CPU image: `docker compose up mojoassistant`
- AMD ROCm GPU image: `docker compose up mojoassistant-rocm`
- HuggingFace model cache reused from host — no re-download on rebuild
- Health check at `/health`

### Local and API LLMs
- local model support via LM Studio or any OpenAI-compatible server
- OpenRouter with multi-account free-API routing and dynamic model detection
- runtime resource pool configuration — add/remove/approve LLM backends live

## Optional Components

### OpenCode Manager
Disabled by default.
Enable only if you want coding-agent orchestration.

See:
- [OpenCode Manager README](app/mcp/opencode/README.md)

## CI / CD

GitHub Actions run on every push:
- **Smoke test** — starts the server, polls `/health`, asserts `status=healthy`
- **Docker build** — builds the CPU image to catch Dockerfile regressions
- **Docker publish** — pushes to `ghcr.io` on `main` and version tags

## Development Notes

Repository policy and coding-agent rules:
- `AGENTS.md`
- `Coding Agents Rules.md`

Recommended local checks before merge:
- run the relevant feature flow manually
- use [MCP Smoke Checklist](docs/guides/MCP_SMOKE_CHECKLIST.md) for live MCP validation
- review release notes for scope drift

## Status

This repository is in active beta development.
The root README is intentionally brief; detailed setup, workflows, and feature-specific guidance live under `docs/`.
