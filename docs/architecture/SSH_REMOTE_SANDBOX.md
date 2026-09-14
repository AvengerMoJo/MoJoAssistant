# SSH Remote Sandbox Backend

Runs OpenCode server mode on a remote host (e.g. a personal business
project machine) and drives it from MoJoAssistant over the tailnet,
async, exactly like the local host backend. The remote host uses your
existing hosted Tailscale tailnet for reachability; Headscale is not
required.

## Architecture

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

## Components

| File | Role |
|------|------|
| `app/scheduler/sandbox/ssh_backend.py` | `SSHRemoteBackend` — lifecycle over SSH |
| `app/scheduler/sandbox/registry.py` | registers the `"ssh"` backend name |
| `app/scheduler/sandbox/manager.py` | `backends.ssh` defaults in `_DEFAULT_CONFIG` |
| `config/sandbox.ssh.example.json` | config schema example (system layer) |
| `~/.memory/config/sandbox.json` | real values (personal layer) |
| `scripts/setup_remote_opencode_host.sh` | optional one-time remote bootstrap (opencode + optional tailnet join) |
| `tests/unit/test_ssh_sandbox_backend.py` | unit tests (all ssh mocked) |

## Setup

### 1. Prepare the remote host

Either let the backend install opencode on first task (default), or
bootstrap ahead of time:

```bash
scripts/setup_remote_opencode_host.sh user@host            # opencode only
scripts/setup_remote_opencode_host.sh user@host --ts-authkey tskey-...
```

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
      "identity_file": "~/.ssh/id_ed25519"
    }
  }
}
```

`host` should be the Tailscale MagicDNS name or 100.x address. `url_host`
(defaults to `host`) is what MoJo dials for the opencode API.

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

## Security notes

- SSH is non-interactive only (`BatchMode=yes`, `StrictHostKeyChecking=accept-new`).
- opencode binds `0.0.0.0` on the remote host but is only reachable through
  the tailnet plus per-task random BasicAuth passwords. Set `bind_host` to
  the remote's tailscale IP for stricter binding.
- The OpenCode password lives in a 0600 env file on the remote
  (`~/.mojo/task_logs/<task>/env`), never in `ps` output or command lines.
- File contents and passwords travel over ssh stdin, never inside remote
  command strings (quoting is asserted by unit tests).
