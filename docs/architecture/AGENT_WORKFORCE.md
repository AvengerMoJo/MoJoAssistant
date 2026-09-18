# Third-Party Agent Workforce — opencode + herdr + tailscale

## Framing: native assistant vs. third-party agent workforce

MoJoAssistant distinguishes two planes for AI coding work:

| | **Native assistant** | **Third-party agent workforce** |
|---|---|---|
| Where it runs | The user's own machine (control-plane host), interactive TUI/CLI | Dedicated managed hosts on the tailnet, headless `opencode serve` |
| Who drives it | A human in the loop (this opencode instance, model `big-pickle`) | Other MCP clients + MoJoAssistant's scheduler — programmatic, unattended |
| Session model | Sessions live/die with the terminal | `Restart=always` systemd units; sessions survive SSH/terminal disconnect |
| Lifecycle | Human starts a run | Spawn / drive / pause / kill via a control plane |
| Reach | Local toolchain, local secrets, human approval | Tailnet mesh, structured credentials, policy-gated sandboxes |
| Best for | Interactive design, code review, 1:1 debugging with the human | Repetitive/parallelizable tasks, scheduled jobs, org-scale execution |

The workforce exists so MoJoAssistant can **delegate and forget** on
dedicated infrastructure instead of consuming the human's terminal and
context window.

## The four components

```
        MCP clients (Claude/Cursor/opencode/codex …)      ← humans + agents
                          │  Streamable HTTP + BasicAuth
                          ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  AgentBridge  (control plane, :8497)                                   │
        │  app/mcp/agent_bridge ・ FastMCP・ agent_run/reply/status/...  │
        └───────────────────────────────┬───────────────────────────────┘
                                        │  OpenCodeClient (httpx, BasicAuth)
                                        ▼
        ┌──────────────────────────  Tailscale mesh  ──────────────────┐
        │  encrypted WireGuard; each node only reachable via tailnet IP │
        └────────────┬────────────────────────────────┬─────────────────┘
                     ▼                                ▼
        ┌────────────────────────┐        ┌────────────────────────────┐
        │ opencode serve (:4096) │        │ opencode serve (:4096)      │
        │ opencode-serve.service │        │ worker-b                    │
        │ (host A, e.g. worker-a)│        │ worker-b's tailnet IP       │
        │ herdr-serve.service    │        │ herdr-serve.service         │
        │ herdr (supervision)    │        │ herdr (supervision)         │
        └────────────────────────┘        └────────────────────────────┘
                     third-party agent workforce (managed hosts)
```

### 1. `opencode serve` — the worker

The deployed agent binary runs headless as `opencode-serve.service`
(a systemd **user** unit):

```ini
[Unit]
Description=opencode server mode (managed by MoJoAssistant)
After=network-online.target

[Service]
Type=simple
EnvironmentFile=%h/.mojo/server.env        # OPENCODE_SERVER_PASSWORD
ExecStart=/home/alex/.local/bin/opencode serve --port 4096 --hostname 0.0.0.0
Restart=always
```

- **`~/.mojo/server.env`** (mode 0600) holds `OPENCODE_SERVER_PASSWORD`;
  every client (`--auto` attaches, OpenCodeClient) authenticates with it.
- Each session is a first-class object: `create_session`, `send_message`,
  `list_sessions`, `delete_session`. Work runs in the host's filesystem
  (`cwd`, `root`) with the host's model/provider config.
- `Restart=always` + **linger** keep it alive independent of any login.

### 2. herdr — the supervisor

`herdr` ("terminal workspace manager for AI coding agents") gives the
human and MoJo a **second, human-grade control surface** on top of the
raw server:

- Persistent named **sessions**, multi-agent **panes**, and
  detach/reattach — live debugging without losing state.
- `herdr --remote <ssh-target> [--session <name>]` — drive a distant
  host's sessions from any tailnet machine.
- `herdr agent list --json` — scripted interrogation for automation.
- Installed as `herdr-serve.service` on managed hosts (headless server
  under systemd, socket-based, `~/.herdr/server.env`).

Division of labor: **AgentBridge = programmatic control surface
(MCP tools); herdr = interactive/human surface (TUI, panes, restore).**

### 3. tailscale — the transport

- A WireGuard mesh: every node (control-plane, worker-a, worker-b, …) is a
  stable overlay IP (`100.x.y.z`) with **no public port exposure**.
- Hosts behind NAT/CGNAT (HKG relays, etc.) are reachable by tailnet IP
  exactly like LAN hosts.
- Tailscale **SSH can gate** access to interactive login where
  desirable — e.g. plain `ssh` to a given worker requires a browser
  approval (`login.tailscale.com/a/<id>`), which keeps hands-on admin
  human-supervised while the mesh itself stays open for services.
- Bind guidance: tailnet-IP binds for control-plane services
  (the control-plane's tailnet IP), never `0.0.0.0` on machines without host
  firewalling.

### 4. AgentBridge — the control plane

`app/mcp/agent_bridge` (FastMCP, Streamable HTTP) is the **single MCP
surface** the workforce exposes to any MCP client:

```
agent_servers        list configured hosts + reachability
agent_status         health-check a host (or a session)
agent_run            create session + send prompt (blocking reply)
agent_reply          continue an existing session
agent_sessions       list sessions on a host
agent_close_session  delete a session on a host
```

One bridge registers **any number of hosts** (N:1) in
`~/.memory/config/agent_bridge.json`; each host maps to its
`OpenCodeClient(url, password)`. Adding an org = adding a registry
entry, no new bridges.

For the interaction with MoJoAssistant's own orchestration see
`AGENT_BRIDGE.md` (client wiring, systemd unit, DNS-rebinding note),
`SSH_REMOTE_SANDBOX.md` (managed-host backend), and the scheduler docs
for scheduled/spawned jobs.

## Deployment model

Provision a new worker with the one-shot bootstrap:

```bash
scripts/setup_remote_opencode_host.sh user@host \
  --ts-authkey <KEY> --managed --managed-bind 0.0.0.0 --managed-port 4096 --herdr
```

This installs opencode, joins the tailnet, writes `~/.mojo/server.env`
(password 0600), installs `opencode-serve.service` (+ herdr), and prints
the resulting tailnet address + next steps. Registration in the bridge is
then just a hosts entry.

## Security model

- **Bridge**: BasicAuth (`opencode:<bridge-password>`) as the only
  client gate; bind tailnet IP; TLS optional via Tailscale HTTPS for
  real deployments.
- **Hosts**: BasicAuth from `~/.mojo/server.env` (0600). Credentials
  travel host-config → OpenCodeClient over the tailnet only; never
  logged. Credentials live in `~/.memory/config/` (personal layer), never
  in `project/config/`.
- **DNS-rebinding**: mcp SDK 1.28's transport security whitelists the
  configured `bind` host; wildcard binds disable host validation.
- **Never** expose a worker's `:4096` or the bridge to the public
  internet; public-Inbound hosting risk is the reason for tailnet binds.

## Current inventory

Real hostnames, Tailscale IPs, and per-host hardware/service details are
personal infrastructure information and are deliberately kept out of
this public repo. See `~/.memory/research/agent_workforce_inventory.md`
(private, not committed) for the actual current inventory.

As of this writing: one control-plane host, three registered workers
(one Linux, one Windows, one on the legacy `backend: "legacy_mcp"` path
described in `AGENT_BRIDGE.md`).

**Ownership boundary:** every host in the bridge registry carries an
`owner` field (`personal` vs `customer`), surfaced by `agent_fleet`.
Customer-owned workers (e.g. infrastructure belonging to a client) must
never be used as personal workforce or for personal experiments — touch
them only when the task is explicitly on behalf of that client, through
channels the customer has agreed to. When extending the registry, always
set `owner` and keep the boundary visible.

## When to use which

- **Native assistant**: the user is present; interactive design, review,
  approvals, working in local repos.
- **Workforce**: schedule it, parallelize it, let it run unattended on
  clean infra, hand results back through session objects. Use MoJoAssistant's
  scheduler to spawn tasks onto remote hosts; use the bridge from any
  MCP client (e.g. this opencode instance's `<worker>-agent` entry)
  to drive a worker mid-task after the human attaches.

See also: `AGENT_BRIDGE.md`, `SSH_REMOTE_SANDBOX.md`, `SANDBOX_SYSTEMS.md`,
`CUBESANDBOX_REBUILD_GUIDE.md`.