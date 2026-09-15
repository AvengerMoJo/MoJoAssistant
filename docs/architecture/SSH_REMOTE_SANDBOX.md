# SSH Remote Sandbox Backend

Runs OpenCode server mode on a remote host (e.g. a personal business
project machine) and drives it from MoJoAssistant over the tailnet,
async, exactly like the local host backend. The remote host uses your
existing hosted Tailscale tailnet for reachability; Headscale is not
required.

Two operating modes:

- **Ephemeral (default)** — a per-task `opencode serve` is spawned on the
  remote host and torn down on kill.
- **Managed (`use_managed: true`)** — one always-on `opencode serve`
  managed by a systemd user service (`Restart=always`, linger enabled)
  hosts all tasks concurrently. Tasks get sessions, not processes. The
  same server can also be exposed to third-party MCP clients through the
  agent bridge (see `AGENT_BRIDGE.md`).

## Architecture (ephemeral mode)

```
scheduler task (config: sandbox_backend=ssh, working_dir=~/projects/x)
       │
       ▼
SandboxManager.acquire() ── backend_override="ssh"
       │
       ▼
SSHRemoteBackend (app/scheduler/sandbox/ssh_backend.py)
       │  ssh (BatchMode, key auth, accept-new)
       ├── detects / installs opencode (bun, else curl installer)
       ├── mkdir working dir + ~/.mojo/task_logs/<task>/
       ├── writes 0600 env file (random per-task OPENCODE_SERVER_PASSWORD,
       │  never on the command line / in ps)
       ├── picks free port in 4600-4699 (remote ss -ltn)
       ├── spawns: nohup setsid opencode serve --port P --hostname 0.0.0.0
       └── pause/resume/kill via remote SIGSTOP/SIGCONT/SIGTERM
       │
       ▼  http://<tailscale-name>:<port>  (BasicAuth, tailnet-only exposure)
OpenCodeClient (app/scheduler/sandbox/opencode_client.py)
       └── sessions / messages / permissions — the normal async agent loop
```

## Architecture (managed mode)

```
                       ┌──────────────────────────────────────────────┐
                       │  remote host  (systemd user)                 │
                       │  opencode-serve.service  (Restart=always)    │
                       │    opencode serve :4096  (bind 0.0.0.0)      │
                       │    → ~/.mojo/server.env   (0600, password)   │
                       └──────────────┬───────────────────────────────┘
                                      │ tailnet + BasicAuth
              ┌───────────────────────┼─────────────────────────┐
              ▼                        ▼                         ▼
  SSHRemoteBackend             agent bridge (FastMCP)      third-party MCP
  use_managed: true           app/mcp/agent_bridge/        clients (Claude
  per-task sessions           python -m …server (:8497)    Desktop, Cursor…)
  on the shared server        agent_run/reply/sessions
```

In managed mode `pause()`/`resume()` are *logical only* — there is no
SIGSTOP on a shared server that must keep serving other tasks. `kill()`
removes the handle (and the task's session is abandoned) without touching
the server.

## Components

| File | Role |
|------|------|
| `app/scheduler/sandbox/ssh_backend.py` | `SSHRemoteBackend` — lifecycle over SSH, both modes |
| `app/scheduler/sandbox/registry.py` | registers the `"ssh"` backend name |
| `app/scheduler/sandbox/manager.py` | `backends.ssh` defaults in `_DEFAULT_CONFIG` |
| `config/sandbox.ssh.example.json` | config schema example (system layer) |
| `~/.memory/config/sandbox.json` | real values (personal layer) |
| `scripts/setup_remote_opencode_host.sh` | one-time remote bootstrap: opencode, optional tailnet join, optional `--managed` service, optional `--herdr` |
| `app/mcp/agent_bridge/` | Streamable-HTTP MCP bridge exposing managed servers to 3rd-party MCP clients |
| `docs/architecture/AGENT_BRIDGE.md` | agent bridge setup + usage |
| `tests/unit/test_ssh_sandbox_backend.py` | unit tests (all ssh mocked) |
| `tests/unit/test_agent_bridge.py` | bridge tool tests (OpenCodeClient mocked) |
| remote: `~/.local/bin/herdr` | herdr v0.9.0 — agent-native terminal multiplexer |
| remote: `~/.config/systemd/user/herdr-serve.service` | headless herdr server (`Restart=always`) |
| remote: `~/.config/opencode/plugins/herdr-agent-state.js` | opencode integration — lifecycle authority inside herdr panes |
| remote: `~/.config/opencode/skills/herdr/SKILL.md` | agent skill: pane layout, output reads, multi-agent awareness |

## herdr supervision layer (complementary to managed mode)

[herdr](https://herdr.dev) is an agent-native terminal multiplexer (like tmux
but designed for coding agents). On managed-mode hosts it runs alongside
`opencode-serve.service` as `herdr-serve.service` (also `Restart=always`,
linger enabled) and provides:

- **Terminal supervision:** herdr tracks every agent pane (`idle`, `working`,
  `blocked`, `done`, `unknown`); `blocked` surfaces approval questions —
  never hunt for the stuck agent.
- **Multi-agent panes:** create workspace → tab → pane layout; start a second
  opencode instance or a helper agent in a sibling pane; read/wait on any pane.
- **Detach/reattach:** detach from herdr TUI with `ctrl+b q`; panes keep
  running; reattach later; restart restores session shape.
- **Remote attach from any machine:** `herdr --remote user@host` (SSH socket
  forwarding, no extra auth needed beyond SSH keys). Falls back to a saved
  machine profile (`herdr machine add <name>`).
- **opencode integration v11:** when opencode runs inside a herdr pane, the
  plugin reports authoritative lifecycle state + native session identity.
  Session restore after server restart: `opencode --session <id>`.

Key distinction: **herdr manages the opencode TUI** (terminal panes, session
restore, lifecycle reads); **`opencode serve` runs the headless HTTP server**
that `SSHRemoteBackend` and the agent bridge talk to. These are orthogonal
surfaces — herdr adds supervision and multi-agent panes without changing the
existing managed-mode HTTP path.

## Setup

### 1. Prepare the remote host

Either let the backend install opencode on first task (default), or
bootstrap ahead of time:

```bash
scripts/setup_remote_opencode_host.sh user@host            # opencode only
scripts/setup_remote_opencode_host.sh user@host --ts-authkey tskey-...
scripts/setup_remote_opencode_host.sh user@host --managed \
    --managed-bind 0.0.0.0 --managed-port 4096
scripts/setup_remote_opencode_host.sh user@host --managed --herdr \
    --managed-bind 0.0.0.0 --managed-port 4096
```

The `--managed` variant installs `opencode-serve.service` (systemd user
unit, `Restart=always`, linger enabled) and writes the shared
`OPENCODE_SERVER_PASSWORD` to `~/.mojo/server.env` (mode 0600). Bind
`0.0.0.0` so the tailnet can reach it; the tailnet + password are the
security boundary.

The `--herdr` flag installs herdr alongside the managed server
(`herdr-serve.service` headless, opencode integration, agent skill).
Access the herdr session from any machine with:
`herdr --remote user@host`.

Requirements on the remote host: bash, `ss` (iproute2), and bun or curl.
Join it to your tailnet (installer script can, or `tailscale up` manually)
and confirm `ssh user@host 'command -v opencode'` works non-interactively
with your key.

### 2. Configure MoJo (personal layer)

Merge into `~/.memory/config/sandbox.json` (schema in
`config/sandbox.ssh.example.json`):

```json
{
  "backends": {
    "ssh": {
      "host": "remote-host.your-tailnet.ts.net",
      "user": "deploy",
      "identity_file": "~/.ssh/id_ed25519",
      "use_managed": true,
      "managed_port": 4096,
      "managed_env_file": "~/.mojo/server.env"
    }
  }
}
```

`host` should be the Tailscale MagicDNS name or 100.x address. `url_host`
(defaults to `host`) is what MoJo dials for the opencode API. In managed
mode the backend reads the password from the remote `managed_env_file`
rather than generating a per-task one, and checks `managed_service` is
`active` (auto-starting it if `Restart=always` hasn't).

### 3. Run a task

```
scheduler create task with config:
  {"sandbox_backend": "ssh", "working_dir": "~/projects/bizbuild",
   "git_url": "git@github.com:you/bizbuild.git"}
```

MoJo SSHes in, spawns `opencode serve` on a free port, and runs the normal
coding-session loop remotely. On completion the sandbox pauses (remote
SIGSTOP) and stays re-attachable via the usual sandbox tools; logs mirror
to `~/.memory/task_logs/<task>/remote_agent.log`.

In managed mode MoJo instead attaches to the always-on
`opencode-serve.service`, gets a session on it, and drives the same loop;
completion marks the handle paused (logically) without freezing other
tasks' sessions on the shared server.

## Security notes

- SSH is non-interactive only (`BatchMode=yes`, `StrictHostKeyChecking=accept-new`).
- opencode binds `0.0.0.0` on the remote host but is only reachable through
  the tailnet plus per-task random BasicAuth passwords. Set `bind_host` to
  the remote's tailscale IP for stricter binding.
- The OpenCode password lives in a 0600 env file on the remote
  (`~/.mojo/task_logs/<task>/env`), never in `ps` output or command lines.
- File contents and passwords travel over ssh stdin, never inside remote
  command strings (quoting is asserted by unit tests).
- herdr sockets (`~/.config/herdr/herdr.sock`) are mode `0700` (user-only).
  `herdr --remote` forwards over SSH — no extra authentication beyond SSH keys.
  The agent skill (`~/.config/opencode/skills/herdr/SKILL.md`) gates on
  `HERDR_ENV=1`: an agent outside a herdr pane refuses to act.
