# MoJoAssistant Installation Guide

---

## Quick Start (Recommended)

MoJoAssistant has complex configuration — resource pool, memory embeddings, storage modules, MCP setup. The easiest way to install is to let an AI agent do it for you.

### Step 1: Install OpenCode

```bash
# Install bun (if not already installed)
curl -fsSL https://bun.sh/install | bash
source ~/.bashrc

# Install OpenCode
bun install -g opencode-ai
```

OpenCode comes with a free model (Big Pickle) — no API key needed.

### Step 2: Clone MoJoAssistant

```bash
git clone --recurse-submodules https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant
```

### Step 3: Ask OpenCode to install it

```bash
opencode
```

Then tell OpenCode:

```
Read the INSTALL.md and install MoJoAssistant for me.
Set up the resource pool, embeddings, .env, and MCP configuration.
```

OpenCode will read the docs, ask you questions about your setup (local vs API models, which features to enable), and configure everything step by step.

### Step 4: Start the server

```bash
python unified_mcp_server.py --mode http --port 8000
```

Verify: `curl http://localhost:8000/health`

---

## Manual Install

For users who prefer to install themselves, or for AI agents following these instructions.

### Requirements

| Requirement | Minimum | Notes |
|---|---|---|
| Python | 3.10+ | 3.12 recommended |
| OS | Linux, macOS | Windows via WSL2 |
| RAM | 2 GB | 4 GB recommended with sentence-transformers |
| Disk | 500 MB | + model cache (~1 GB for default embedding model) |
| GPU | Not required | All inference can be offloaded to LM Studio or remote APIs |

### Option A — Docker

```bash
git clone --recurse-submodules https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant
cp .env.example .env
# Edit .env — set DASHBOARD_PASSWORD, MCP_API_KEY
docker compose up
```

### Option B — Python venv

```bash
git clone --recurse-submodules https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-runtime.txt
pip install --no-cache-dir submodules/dreaming-memory-pipeline/
cp .env.example .env
# Edit .env — configure as needed (see Environment Variables below)
python unified_mcp_server.py --mode http --port 8000
```

### Option C — Systemd service (Linux)

After completing Option B:

```bash
./scripts/install_service.sh
```

This installs and starts a persistent systemd user service. Check status:

```bash
systemctl --user status mojoassistant
```

### Option D — Setup wizard (interactive)

```bash
python app/interactive-cli.py --setup
```

The wizard uses an AI model to guide you through configuration conversationally. Downloads Qwen3-1.7B by default (~1.2 GB).

### Option E — Install script

```bash
./scripts/install.sh
```

Checks Python, creates venv, installs deps, runs preflight checks (tmux, node, cargo), creates startup scripts.

---

## First Run Checklist

- [ ] `curl http://localhost:8000/health` returns OK
- [ ] Dashboard accessible at `http://localhost:8000/dashboard`
- [ ] At least one role loaded (check dashboard)
- [ ] Test task dispatched and completed
- [ ] Dreaming reachable (`curl http://localhost:8000/api/dreaming`)

---

## Environment Variables

Copy `.env.example` to `.env`. All optional — the server starts with defaults.

### Core Server

| Variable | Default | Required | Description |
|---|---|---|---|
| `SERVER_HOST` | `0.0.0.0` | No | Bind address |
| `SERVER_PORT` | `8000` | No | HTTP port |
| `MCP_API_KEY` | `demo_key_for_development` | **Yes (prod)** | API key for MCP authentication |
| `MCP_REQUIRE_AUTH` | `false` | No | Set `true` in production |
| `DASHBOARD_PASSWORD` | — | No | Dashboard UI password; falls back to `MCP_API_KEY` |
| `MOJO_BASE_URL` | — | No | Public URL; required for ntfy reply buttons |
| `ENVIRONMENT` | `development` | No | `development` or `production` |

### LLM Backends

Configure at least one. See `config/llm_config.json.example` for full model catalog.

| Variable | Description |
|---|---|
| `LMSTUDIO_BASE_URL` | LM Studio URL (e.g. `http://localhost:8080/v1`) |
| `LMSTUDIO_API_KEY` | LM Studio bearer token |
| `OPEN_ROUTER_KEY` | OpenRouter API key (100+ models) |
| `LOCAL_MODEL_PATH` | Path to local GGUF model files |

### Memory & Embeddings

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model for semantic search |
| `VECTOR_STORE` | `qdrant` | Vector store backend |
| `MEMORY_PATH` | `~/.memory` | Root directory for memory and knowledge storage |

### Optional Features

| Variable | Default | Description |
|---|---|---|
| `ENABLE_OPENCODE` | `false` | Enable OpenCode coding agent manager |
| `ENABLE_CLAUDE_CODE` | `false` | Enable Claude Code CLI subprocess manager |
| `NTFY_TOKEN` | — | ntfy.sh account token for push notifications |
| `GOOGLE_API_KEY` | — | Google Custom Search API key |
| `OAUTH_ENABLED` | `false` | Enable OAuth 2.1 resource server |

### Discord Community Bot

| Variable | Default | Description |
|---|---|---|
| `ENABLE_DISCORD_BOT` | `false` | Set `true` to start the bot with the main service |
| `DISCORD_BOT_TOKEN` | — | Bot token from Discord Developer Portal |
| `DISCORD_COMMUNITY_ROLE_ID` | `community_host` | MoJo role that answers questions |

---

## Supported Models

MoJoAssistant is model-agnostic. Any OpenAI-compatible endpoint works.

| Backend | Models | Config |
|---|---|---|
| LM Studio | Qwen3, Llama 3.x, Mistral, Phi-4, any GGUF | `LMSTUDIO_BASE_URL` + `LMSTUDIO_API_KEY` |
| OpenRouter | Claude, GPT-4o, Gemini, Llama, Qwen, Mistral | `OPEN_ROUTER_KEY` |
| Local GGUF | Any llama.cpp-compatible model | `LOCAL_MODEL_PATH` |

---

## Connecting MCP Clients

### Claude Desktop

```json
{
  "mcpServers": {
    "mojo": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_API_KEY"
      }
    }
  }
}
```

### Claude Code CLI

```bash
claude --mcp-config /path/to/mojo-mcp.json
```

### MiMoCode

```bash
mimo mcp add
```

Use `mimocode.json` in project root with `type: "remote"`, `oauth: {}`.

---

## Optional Plugins

### tmux Terminal MCP

Persistent terminal sessions for agents.

```bash
sudo apt install tmux          # or: brew install tmux
cargo install tmux-mcp-rs
```

See `docs/guides/TMUX_MCP_SETUP.md`.

### Browser MCP (Webwright default, Playwright available)

| Backend | Style | Install |
|---|---|---|
| **Webwright** (default) | Code-as-action | `pip install webwright && playwright install chromium` |
| **Playwright MCP** | Step-by-step | `npm install -g @playwright/mcp && npx playwright install chromium` |

Both are enabled by default. Webwright is preferred for agentic tasks (agents write Playwright scripts). See `docs/guides/BROWSER_MCP_SETUP.md`.

### Google Workspace

Calendar, Drive, Gmail via the `gws` CLI. See `docs/guides/GOOGLE_WORKSPACE_SETUP.md`.

### ntfy Push Notifications

See `docs/guides/NOTIFICATIONS_SETUP.md`.

---

## Feature Surface

### Stable (works out of the box)

- Scheduler daemon (task queue, HITL, resource pool)
- Memory search (local semantic search via sentence-transformers)
- MCP tool surface (14 hub tools)
- Policy checker (behavioral + content enforcement)
- Role system (personas, knowledge isolation)
- Dashboard (event log, tasks, role chat)

### Experimental (extra setup needed)

- Agent execution (requires LLM endpoint)
- Terminal tools (requires tmux + tmux-mcp-rs)
- Browser tools (requires Webwright or Playwright)
- Discord community bot (requires DISCORD_BOT_TOKEN)
- Google Workspace (requires gcloud + gws)
- CubeSandbox (requires E2B_API_URL + E2B_API_KEY)

---

## Capacity Limits

| Limit | Default |
|-------|---------|
| Concurrent tasks | 3 |
| Task iterations | 10 per task |
| Task retries | 3 |
| Scheduler tick | 60 seconds |
| Tool calls per turn | 10 |
| Sub-task depth | 2 levels |
| Event log | 500 events (circular) |

---

## Security

By default: `MCP_REQUIRE_AUTH=false`, `DASHBOARD_PASSWORD=change_me`. This is intentional for personal use on a trusted machine.

If exposing to a network:
1. Set `MCP_REQUIRE_AUTH=true`
2. Set `MCP_API_KEY` to a strong random value: `openssl rand -hex 32`
3. Set `DASHBOARD_PASSWORD` to something other than `change_me`

---

## Upgrading

```bash
git pull
pip install -r requirements-runtime.txt
# restart the server
```

No database migrations needed. Config files are backwards-compatible.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Health returns 500 | Check `journalctl --user -u mojoassistant` or `docker logs mojoassistant` |
| LM Studio connection fails | Verify `base_url` in `config/llm_config.json` matches your server |
| Dashboard won't load | Ensure `DASHBOARD_PASSWORD` is set in `.env` |
| Task fails "not found" | Check task goal references real files/paths |
| Task fails "blocked by policy" | Check role capabilities and policy violation log |
| Task fails "rate limit" | Wait and retry; try a different LLM tier |
