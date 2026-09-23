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
   agent_fleet / agent_fleet_summary   (dashboard: metadata + availability,
                                         every host regardless of backend)
        │  OpenCodeClient (httpx, BasicAuth) — opencode_serve hosts
        │  raw MCP handshake (httpx)         — legacy_mcp hosts
        ▼
   remote host(s): opencode-serve.service  (systemd, always-on, :4096)
                   or a legacy_mcp host (different wire protocol,
                   availability-only — e.g. a legacy host on :4097)
```

A host's `backend` field (default `"opencode_serve"`) selects how
`agent_fleet`/`agent_servers` check it — see
`docs/specs/agent_workforce_dashboard_spec.md`. A `"legacy_mcp"` host
never goes through `OpenCodeClient`; only its reachability is checked,
via a raw MCP `initialize` handshake. `agent_run`/`agent_reply`/
`agent_sessions` still assume the opencode REST API and will error
against a `legacy_mcp` host — the fleet dashboard is what actually
supports mixed backends today, not the full agent lifecycle.

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

> **DNS-rebinding guard (mcp SDK 1.28).** `FastMCP.streamable_http_app()`
> auto-enables host validation when the default `host` is a loopback
> address, rejecting any request whose `Host` header isn't
> `127.0.0.1`/`localhost`/`[::1]` with `421 Misdirected Request`. When the
> bridge binds a tailnet IP, `app/mcp/agent_bridge/server.py:_ensure()`
> whitelists the configured `bind` address via
> `TransportSecuritySettings(allowed_hosts=[...])`. Wildcard `0.0.0.0`
> binds disable host validation (BasicAuth remains the gate).

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

## herdr as alternate control surface

On hosts running `herdr-serve.service` alongside `opencode-serve.service`,
the **herdr CLI over SSH** provides an interactive alternative to the MCP
bridge — useful for live debugging, multi-agent panes, and session
restore (detached sessions survive SSH disconnects). For scripted
interactions use the CLI with JSON output (`herdr <group> --json`).

```bash
# interactive: open herdr TUI for the remote session
herdr --remote user@host

# scripted: list agents in JSON for a calling script
herdr agent list --json
```

The MCP bridge (this file) is the right surface for programmatic tool
calls from other MCP clients; herdr is the right surface for humans
and for direct pane supervision.

## Security notes

- The bridge should sit on loopback/tailnet and front it with Tailscale
  Serve / a Cloudflare tunnel if it must be reachable off-host.
- BasicAuth is the only client gate; put the bridge behind TLS (e.g.
  Tailscale HTTPS) for real deployments.
- Host credentials travel from config into OpenCodeClient over HTTP on
  the tailnet — never log them.

## Reference deployment

The production layout for the third-party agent workforce (see
`AGENT_WORKFORCE.md`) runs a **central bridge on one control-plane
host**, bound to the tailnet, serving every managed opencode host from
one registry.

```
control-plane-host (Tailscale <control-plane-tailnet-ip>)
  agent-bridge.service  →  python -m app.mcp.agent_bridge
  bind <control-plane-tailnet-ip>:8497  BasicAuth  ~/.memory/config/agent_bridge.json
        │ hosts:{worker-a: http://<worker-a-tailnet-ip>:4096, ...}
        ▼
Tailscale mesh
        ▼
worker-a (100.x.y.z)
  opencode-serve.service  →  opencode serve :4096  (OPENCODE_SERVER_PASSWORD)
  herdr-serve.service     →  herdr server (supervision, panes)
```

> Real hostnames/IPs for this deployment are personal infrastructure
> details and are deliberately **not** in this public repo — see
> `~/.memory/research/agent_workforce_inventory.md` (private, per-host,
> not committed) for the actual current values. This file documents the
> pattern only.

### systemd unit (control-plane host, `~/.config/systemd/user/agent-bridge.service`)

```ini
[Unit]
Description=MoJo Assistant agent bridge MCP (managed by MoJoAssistant)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=<path-to-MoJoAssistant-checkout>
Environment=PYTHONPATH=<path-to-MoJoAssistant-checkout>
ExecStart=<python-interpreter> -m app.mcp.agent_bridge
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

### config (`~/.memory/config/agent_bridge.json`, mode 0600)

```json
{
  "bind": "<control-plane-tailnet-ip>",
  "port": 8497,
  "password": "<bridge-basic-auth-password>",
  "hosts": {
    "worker-a": {
      "base_url": "http://<worker-a-tailnet-ip>:4096",
      "password": "<OPENCODE_SERVER_PASSWORD>"
    }
  }
}
```

Bind the **tailnet IP, not `0.0.0.0`** — a worker may have a public IP,
but the control node should stay tailnet-only so the bridge is
unreachable from the public internet while still serving every tailnet
device.

### opencode client wiring (`~/.config/opencode/opencode.json`)

```json
"worker-a-agent": {
  "type": "remote",
  "url": "http://<control-plane-tailnet-ip>:8497/mcp",
  "enabled": true,
  "headers": {
    "Authorization": "Basic <base64(opencode:bridge-password)>"
  }
}
```

### verification

```bash
# initialize → 200 + mcp-session-id header, then:
curl -s -X POST http://<control-plane-tailnet-ip>:8497/mcp \
  -H "Authorization: Basic <base64(opencode:bridge-password)>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <sid>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
# tools: agent_servers agent_status agent_run agent_reply agent_sessions
#        agent_close_session agent_fleet agent_fleet_summary
```

Then `tools/call agent_run {server: worker-a, prompt: "..."}` returns a
live session reply (`session_id` + text) proving the full chain: client
→ bridge → tailscale → `opencode :4096`.

### legacy `opencode-mcp-tool` hosts

An older Node/Express bridge (`opencode_run/opencode_reply/...`,
`serverInfo "opencode-agent"`) predates this FastMCP bridge; its source
lives outside this repo. AgentBridge's `agent_*` tools are the functional
superset for any host that runs real `opencode serve`.

A host still running that old bridge can be registered in
`agent_bridge.json` with `"backend": "legacy_mcp"` and a `base_url`
pointing straight at its actual MCP mount path (e.g.
`http://<tailnet-ip>:4097/mcp` — not the bare host:port, since a
legacy_mcp host's base_url is used as-is, nothing here constructs REST
paths on top of it). `agent_fleet`/`agent_servers` show its real
reachability via a raw MCP `initialize` handshake — the
opencode-client-shaped tools (`agent_run`, `agent_reply`, `agent_sessions`)
still don't work against it and will error if called against a
legacy_mcp host. Full retirement of the legacy endpoint (porting its
actual agent-lifecycle calls onto this bridge) is still open — what's
here only extends the *dashboard*, not full functional parity.