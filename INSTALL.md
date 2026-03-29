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

## Running Tests

```bash
pip install pytest pytest-asyncio
python3 -m pytest tests/smoke/ -q
```

All smoke tests run offline — no network or LLM calls required.

## Upgrading

```bash
git pull
pip install -r requirements-runtime.txt   # picks up new dependencies
# restart the server
```

No database migrations are needed. Config files are backwards-compatible; new keys are added with defaults.
