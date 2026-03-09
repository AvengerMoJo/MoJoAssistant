# MoJoAssistant

MoJoAssistant is a personal AI memory and workflow system.

It combines:
- persistent memory and knowledge retrieval
- an MCP server for AI clients
- local and API-backed LLM routing
- scheduler and agentic task execution
- optional coding-agent management

Current release: `v1.1.7-beta`

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

### 1. Clone and enter the repo

```bash
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant
```

### 2. Run the setup wizard

```bash
python app/interactive-cli.py --setup
```

### 3. Start using it

Interactive CLI:

```bash
./run_cli.sh
```

MCP server:

```bash
./run_mcp.sh
```

Manual server start:

```bash
python unified_mcp_server.py --mode stdio
python unified_mcp_server.py --mode http --port 8000
```

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
- `scheduler_add_task`
- `scheduler_get_task`
- `task_session_read`
- `resource_pool_status`

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

### Architecture and Design
- [System Overview](docs/architecture/SYSTEM_README.md)
- [Scheduler Architecture](docs/architecture/SCHEDULER_ARCHITECTURE.md)
- [Dreaming Specification](docs/architecture/DREAMING_SPECIFICATION.md)

### Releases
- [v1.1.7-beta Release Notes](docs/releases/RELEASE_NOTES_v1.1.7-beta.md)
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
- scheduled tasks
- agentic tasks
- `normal`, `deep_research`, and `parallel_discovery` modes
- review reports with human-in-the-loop decision points

### Local and API LLMs
- local model support
- LM Studio support
- OpenRouter and multi-account free-api routing
- runtime resource pool configuration

## Optional Components

### OpenCode Manager
Disabled by default.
Enable only if you want coding-agent orchestration.

See:
- [OpenCode Manager README](app/mcp/opencode/README.md)

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
