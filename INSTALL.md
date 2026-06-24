# MoJoAssistant — Installation

## Requirements

| Requirement | Minimum | Notes |
|---|---|---|
| Python | 3.10+ | 3.12 recommended |
| OS | Linux, macOS | Windows via WSL2 |
| RAM | 2 GB | 4 GB recommended with sentence-transformers |
| Disk | 500 MB | + model cache (~1 GB for default embedding model) |
| GPU | Not required | All inference can be offloaded to LM Studio or remote APIs |

## Quick Start

```bash
git clone https://github.com/yourusername/MoJoAssistant.git
cd MoJoAssistant
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements-runtime.txt
cp .env.example .env
# Edit .env — minimum: set MCP_API_KEY to something secret
python app/main.py
```

Server starts at `http://localhost:8000`. MCP endpoint: `http://localhost:8000/mcp`.

## Environment Variables

Copy `.env.example` to `.env`. The table below covers every variable. Optional variables can be left commented out.

### Core Server

| Variable | Default | Required | Description |
|---|---|---|---|
| `SERVER_HOST` | `0.0.0.0` | No | Bind address |
| `SERVER_PORT` | `8000` | No | HTTP port |
| `MCP_API_KEY` | `demo_key_for_development` | **Yes (prod)** | Bearer token for MCP authentication |
| `MCP_REQUIRE_AUTH` | `false` | No | Set `true` in production |
| `DASHBOARD_PASSWORD` | — | No | Dashboard UI password; falls back to `MCP_API_KEY` |
| `MOJO_BASE_URL` | — | No | Public URL (e.g. `https://mojo.example.com`); required for ntfy reply buttons |
| `ENVIRONMENT` | `development` | No | `development` or `production` |
| `DEBUG` | `false` | No | Verbose logging |

### LLM Backends

MoJoAssistant supports multiple LLM backends. Configure at least one.

| Variable | Description |
|---|---|
| `LMSTUDIO_BASE_URL` | LM Studio OpenAI-compatible base URL (e.g. `http://localhost:8080/v1`) |
| `LMSTUDIO_API_KEY` | LM Studio bearer token |
| `LMSTUDIO_API_KEY_FILE` | Path to file containing the LM Studio key |
| `OPEN_ROUTER_KEY` | OpenRouter API key (access to 100+ models) |
| `LOCAL_MODEL_PATH` | Path to local GGUF model files |

See `config/llm_config.json.example` for the full model catalog configuration.

### Memory & Embeddings

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model for semantic search |
| `VECTOR_STORE` | `qdrant` | Vector store backend (`qdrant`) |
| `MEMORY_PATH` | `~/.memory` | Root directory for memory and knowledge storage |
| `KNOWLEDGE_PATH` | `~/.memory/knowledge` | Role knowledge base root |
| `MAX_CONTEXT_ITEMS` | `10` | Max items returned per memory/knowledge search |

### Optional Features

| Variable | Default | Description |
|---|---|---|
| `ENABLE_OPENCODE` | `false` | Enable OpenCode coding agent manager |
| `OPENCODE_BIN` | `opencode` | Path to opencode binary |
| `CODING_AGENT_MCP_BIN` | `coding-agent-mcp` | Path to coding-agent-mcp binary |
| `ENABLE_CLAUDE_CODE` | `false` | Enable Claude Code CLI subprocess manager |
| `CLAUDE_BIN` | `claude` | Path to `claude` binary |

### Notifications (ntfy)

| Variable | Description |
|---|---|
| `NTFY_TOKEN` | ntfy.sh account token for protected topics |

Configure notification adapters in `config/notifications_config.json` (copy from `.example`). See `docs/guides/NOTIFICATIONS_SETUP.md`.

### Search

| Variable | Description |
|---|---|
| `GOOGLE_API_KEY` | Google Custom Search API key |
| `GOOGLE_SEARCH_ENGINE_ID` | Programmable Search Engine ID |

### OAuth 2.1 (Claude Connectors)

| Variable | Default | Description |
|---|---|---|
| `OAUTH_ENABLED` | `false` | Enable OAuth 2.1 resource server |
| `OAUTH_ISSUER` | — | Token issuer URL |
| `OAUTH_AUDIENCE` | — | Expected audience claim |
| `OAUTH_JWKS_URI` | — | JWKS endpoint for token verification |

## Supported Models

MoJoAssistant is model-agnostic. Any OpenAI-compatible endpoint works. Tested configurations:

| Backend | Models | Config |
|---|---|---|
| LM Studio | Qwen3, Llama 3.x, Mistral, Phi-4, any GGUF | `LMSTUDIO_BASE_URL` + `LMSTUDIO_API_KEY` |
| OpenRouter | Claude, GPT-4o, Gemini, Llama, Qwen, Mistral | `OPEN_ROUTER_KEY` |
| Local GGUF | Any llama.cpp-compatible model | `LOCAL_MODEL_PATH` |

Declare models in `config/llm_config.json`. The resource pool picks available models at runtime — no restart required when adding new ones.

## Optional Dependencies

`requirements-runtime.txt` covers everything needed to run the server. Additional packages unlock optional features:

| Package | Feature | Install |
|---|---|---|
| `prompt_toolkit` | Enhanced interactive CLI | `pip install prompt_toolkit` |
| `psutil` | Process monitoring for coding agent manager | `pip install psutil` |
| `coding-agent-mcp` | OpenCode/Claude Code agent integration | Install from source |
| `sentence-transformers` | Local embedding model | Included in requirements-runtime.txt |

The server starts and runs normally without any of these — missing packages are detected at import time and the relevant feature is silently disabled.

If you installed with `pip install .`, add Git features with:
`pip install .[git]`

For local inference dependencies (torch/transformers/llama.cpp), install:
`pip install .[local-inference]`

## Connecting Claude Desktop / Claude Code

Add MoJoAssistant as an MCP server in `claude_desktop_config.json`:

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

For Claude Code CLI:

```bash
claude --mcp-config /path/to/mojo-mcp.json
```

Where `mojo-mcp.json` contains the same server definition. A pre-built example is at `config/claude_desktop_config.json`.

## Optional Plugins

### Discord Community Bot

MoJoAssistant can run a Discord bot that answers community support questions using the role-chat backend.

**Required env vars** (add to `.env`):

| Variable | Default | Description |
|---|---|---|
| `ENABLE_DISCORD_BOT` | `false` | Set `true` to start the bot with the main service |
| `DISCORD_BOT_TOKEN` | — | Bot token from [Discord Developer Portal](https://discord.com/developers/applications) |
| `DISCORD_COMMUNITY_ROLE_ID` | `community_host` | MoJo role that answers questions |
| `DISCORD_MENTION_ONLY` | `true` | Only respond when @mentioned |
| `DISCORD_MAX_PROMPT_CHARS` | `2000` | Max characters accepted per message |

**Quick setup:**

1. Create a bot at https://discord.com/developers/applications and copy the token
2. Add the env vars above to `.env`
3. Copy the role template:
   ```bash
   mkdir -p ~/.memory/config/roles
   cp config/examples/roles/community_host.example.json ~/.memory/config/roles/community_host.json
   ```
4. Restart MoJoAssistant

See `docs/integrations/DISCORD_COMMUNITY_ASSISTANT_SPEC.md` for the full security model and operational rules.

### tmux Terminal MCP

Persistent terminal sessions for agents — run commands, manage windows, read output.

**Requirements:** tmux + Rust toolchain (cargo)

```bash
sudo apt install tmux          # or: brew install tmux
cargo install tmux-mcp-rs
```

Enabled by default in `config/mcp_servers.json`. See `docs/guides/TMUX_MCP_SETUP.md` for full setup and troubleshooting.

### Browser MCP (Playwright or Webwright)

Browser automation for agents — two backends available:

| Backend | Style | Install |
|---|---|---|
| **Playwright MCP** | Step-by-step (click, type, snapshot) | `npm install -g @playwright/mcp && npx playwright install chromium` |
| **Webwright** | Code-as-action (agent writes scripts) | `pip install webwright && playwright install chromium` |

Playwright is enabled by default. Webwright is available as an alternative — both share the `browser` tool category. See `docs/guides/BROWSER_MCP_SETUP.md` for choosing between them.

### Google Workspace

Calendar, Drive, Gmail via the `gws` CLI. See `docs/guides/GOOGLE_WORKSPACE_SETUP.md`.

### ntfy Push Notifications

Push alerts to your phone. See `docs/guides/NOTIFICATIONS_SETUP.md`.

---

## Feature Surface: Stable vs Experimental

Every feature is labelled so you know what works on a clean install and what needs extra setup.

### Stable (no LLM or network required)

| Feature | What it does |
|---|---|
| Scheduler daemon | Task queue, HITL inbox, resource pool |
| Memory search | Local semantic search via sentence-transformers |
| MCP tool surface | 12+ tools available to Claude |
| Policy checker | Behavioral + content policy enforcement |
| Role system | Persona management, knowledge isolation |
| HITL inbox | Human-in-the-loop task review |
| Audit trail | Append-only action log |
| Plugin SDK | Scaffold and validate third-party provider modules |

### Experimental (extra setup needed)

| Feature | Requirement |
|---|---|
| Agent execution | LLM reachable at configured endpoint (LM Studio, Ollama, OpenRouter) |
| Coding agent bridge | `claude` or `opencode` binary in PATH |
| Terminal tools (tmux) | `tmux` + `cargo install tmux-mcp-rs` — see `docs/guides/TMUX_MCP_SETUP.md` |
| Browser tools | Playwright (`npx @playwright/mcp@latest`) or Webwright (`pip install webwright`) — see `docs/guides/BROWSER_MCP_SETUP.md` |
| Discord community bot | `DISCORD_BOT_TOKEN` in `.env` — see Discord section above |
| Google Workspace | `gcloud` + `gws` CLI — see `docs/guides/GOOGLE_WORKSPACE_SETUP.md` |
| ntfy notifications | ntfy.sh account or self-hosted instance — see `docs/guides/NOTIFICATIONS_SETUP.md` |
| Voice pipeline | `mojo-voice` submodule configured |
| CubeSandbox | `E2B_API_URL` + `E2B_API_KEY` in env or `infra_context.json` |
| Cloudflared tunnel | `cloudflared` installed, for remote Claude.ai access |

## Capacity Limits

MoJoAssistant is designed for personal use. These are the tested defaults:

| Limit | Default | Where |
|-------|---------|-------|
| Concurrent tasks | 3 | `Scheduler(max_concurrent=3)` |
| Task iterations (agentic loop) | 10 per task | `Task.max_iterations` |
| Budget extension grant | 20 max per request | `_BUDGET_EXTENSION_MAX_GRANT` |
| Task retries | 3 | `Task.max_retries` |
| Scheduler tick interval | 60 seconds | `Scheduler(tick_interval=60)` |
| Tool calls per turn | 10 max | `_MAX_CALLS_PER_TURN` in agentic executor |
| Sub-task dispatch depth | 2 levels | `CapabilityRegistry.MAX_DISPATCH_DEPTH` |
| Event log size | 500 events (circular) | `EventLog.MAX_EVENTS` |
| Role chat iterations | 5 per exchange | `MAX_CHAT_ITERATIONS` |
| Role chat history | 10 turns carried | `MAX_HISTORY_TURNS` |
| Knowledge units injected | 8 max | `MAX_KU_ITEMS` |
| Bash command timeout | 60 seconds | safety policy |
| Memory search results | 10 default, 20 max | `MAX_CONTEXT_ITEMS` |

**What this means in practice:**
- 3 agents can run simultaneously; additional tasks queue and wait
- Each agent gets 10 LLM calls per task (request more via HITL if needed)
- Old events are dropped after 500 (audit log is separate and never drops)
- Sub-agent delegation goes 2 levels deep max (A→B→C, no deeper)

**Not tested for:**
- More than 10 concurrent tasks
- More than 50 queued tasks
- Context windows above 128K tokens (works, but context trimming may lose detail)

## Security & Authentication

MoJoAssistant is local-first. By default:

- `MCP_REQUIRE_AUTH=false` — no authentication required for MCP endpoints
- `DASHBOARD_PASSWORD=change_me` — dashboard is open until you set a password

**This is intentional for personal use on a trusted machine.** The threat model assumes:
- The machine is yours and physically secured
- No untrusted users have network access to the MCP port
- You are the only person using the system

**If you expose MoJo to a network** (cloudflared tunnel, shared LAN, server):
1. Set `MCP_REQUIRE_AUTH=true` in `.env`
2. Set `MCP_API_KEY` to a strong random value: `openssl rand -hex 32`
3. Set `DASHBOARD_PASSWORD` to something other than `change_me`
4. Consider enabling OAuth: `OAUTH_ENABLED=true` (see `.env.example`)

The policy pipeline, audit trail, and role-based data isolation are always active regardless of auth settings — they protect against agent misbehavior, not network adversaries.

## Running Tests

```bash
pip install pytest pytest-asyncio

# CI gate — stable only (no LLM or network):
python3 -m pytest tests/smoke/ -m stable -q

# Full picture (shows what needs extra setup):
python3 -m pytest tests/smoke/ -q
```

All stable smoke tests run fully offline — no network or LLM calls required.

## Upgrading

```bash
git pull
pip install -r requirements-runtime.txt   # picks up new dependencies
# restart the server
```

No database migrations are needed. Config files are backwards-compatible; new keys are added with defaults.

## Troubleshooting Task Failures

When a task fails, the dashboard and `scheduler(action="get")` show a `last_error` message.
Below are the common failure categories and what to do about them.

| Error pattern | Category | What it means | What to do |
|---|---|---|---|
| "not found", "does not exist", "404" | `missing_resource` | Agent looked for something that isn't there | Check the task goal references real files/paths |
| "blocked by policy", "permission denied" | `missing_permission` | Safety policy blocked a tool call | Check role capabilities; see policy violation log |
| "rate limit", "timeout", "503", "429" | `external_unavailable` | External API (LLM, search) is down or throttled | Wait and retry; check API key; try a different tier |
| "unclear", "ambiguous", "clarify" | `ambiguous_goal` | Agent couldn't understand the task | Rewrite the task goal more specifically |
| "not supported", "requires browser" | `wrong_tool` | Agent tried something its tools can't do | Enable the right capability (browser, terminal) |
| "don't know", "no information" | `knowledge_gap` | Agent has no relevant memory/knowledge | Feed it context via `add_conversation` first |
| (empty or generic error) | `unknown` | Agent exhausted iterations without finishing | Grant more iterations via HITL reply, or simplify the goal |

**Viewing task details:**
```
Use the scheduler tool with action="get" and task_id="<id>"
Use the task_session_read tool to see the full conversation log
```

**Cron tasks:** A cron task that fails will reschedule to its next window automatically.
The `last_error` from a failed run is preserved until the next successful run clears it.
