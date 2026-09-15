# Agent Bridge — MCP Streamable-HTTP proxy to Managed OpenCode Agents

Enables **third-party MCP clients** (Claude Desktop, Cursor, Witsy,
MCP-compatible tools) to drive the same always-on OpenCode agents that
MoJoAssistant's `ssh` backend manages. A single FastMCP server exposes
the agent lifecycle as MCP tools, proxying to any number of distant
`opencode serve` instances over the tailnet.

## Architecture

```
MCP client (Claude Desktop, Cursor, …)     MCP client (MoJo host backend)
        │  Streamable HTTP (BasicAuth)            │
        ▼                                        ▼
   app/mcp/agent_bridge/server.py      (FastMCP, Streamable-HTTP transport)
   agent_run / agent_reply / agent_sessions / agent_status / agent_servers
        │  OpenCodeClient (httpx, BasicAuth)
        ▼
   remote host(s): opencode-serve.service  (systemd, always-on, :4096)
```

One bridge serves any number of hosts from the registry config; each host
is a `use_managed: true` SSH remote backend target (see
`SSH_REMOTE_SANDBOX.md`).

The mcp Python SDK (1.28) manages MCP sessions natively, so a single
FastMCP server (rather than the Node guide's per-session McpServer
workaround) hosts every MCP client concurrently.

## Components

| File | Role |
|------|------|
| `app/mcp/agent_bridge/server.py` | FastMCP server + MCP tools + `build_app()` |
| `app/mcp/agent_bridge/registry.py` | `HostRegistry` — one `OpenCodeClient` per host |
| `app/mcp/agent_bridge/config.py` | loads `~/.memory/config/agent_bridge.json` |
| `app/mcp/agent_bridge/__main__.py` | `python -m app.mcp.agent_bridge` run entry |
| `config/agent_bridge.example.json` | config schema example |
| `tests/unit/test_agent_bridge.py` | tool unit tests (OpenCodeClient mocked) |

## Config

Merge into `~/.memory/config/agent_bridge.json` (personal layer):

```json
{
  "bind": "0.0.0.0",
  "port": 8497,
  "password": "change-me-bridge-password",
  "hosts": {
    "orgvm-memoria-hk001": {
      "base_url": "http://orgvm-memoria-hk001:4096",
      "password": "<OPENCODE_SERVER_PASSWORD from ~/.mojo/server.env>"
    }
  }
}
```

- The **bridge password** authenticates MCP clients to the bridge.
- Each **host password** is that host's `OPENCODE_SERVER_PASSWORD`,
  read from `~/.mojo/server.env` on the remote (written by
  `setup_remote_opencode_host.sh --managed`).

## Run

```bash
python -m app.mcp.agent_bridge.server --host 0.0.0.0 --port 8497
```

The `password` field in config is used for BasicAuth on the bridge. If
empty, a random one is generated per start and printed to stderr —
persist it in the config for stable clients.

If the bridge has no `password` it starts anyway; clients must present
`Basic base64(opencode:<password>)`.

Mount into an existing FastAPI app:

```python
from app.mcp.agent_bridge.server import build_app
# build_app() returns a Starlette app; mount at /mcp
```

## MCP client registration

### Claude Desktop (`~/.claude/mcp_servers.json`)

```json
{
  "mcpServers": {
    "agent-bridge": {
      "url": "http://127.0.0.1:8497/mcp",
      "headers": {
        "Authorization": "Basic <base64(opencode:bridge-password)>"
      }
    }
  }
}
```

### opencode (`~/.config/opencode/opencode.json`)

```json
{
  "mcp": {
    "agent-bridge": {
      "type": "remote",
      "url": "http://127.0.0.1:8497/mcp",
      "enabled": true,
      "headers": { "Authorization": "Basic <base64(opencode:bridge-password)>" }
    }
  }
}
```

### Codex (`~/.codex/config.toml`)

```toml
[mcp_servers.agent-bridge]
url = "http://127.0.0.1:8497/mcp"
headers = { "Authorization": "Basic <base64(opencode:bridge-password)>" }
```

## Security notes

- The bridge should sit on loopback/tailnet and front it with Tailscale
  Serve / a Cloudflare tunnel if it must be reachable off-host.
- BasicAuth is the only client gate; put the bridge behind TLS (e.g.
  Tailscale HTTPS) for real deployments.
- Host credentials travel from config into OpenCodeClient over HTTP on
  the tailnet — never log them.