# Headscale Mesh Networking Setup (Phase 1)

Self-hosted Tailscale-compatible mesh VPN control plane. Gives MoJoAssistant
a self-controlled internal DNS (`*.mojo.internal`) instead of depending on
external tunnels for node-to-node reachability. See
`~/.claude/projects/-home-alex-Development-Personal-MoJoAssistant/memory/project_network_provider_vision.md`
for the full vision (multi-node mesh, sandbox VM integration — later phases).

**Phase 1 scope**: install Headscale, join this machine as the first node,
wire in the `NetworkProvider` module and health check. Does **not** touch
CubeSandbox, the cloudflared tunnel, or `.env`'s `E2B_*` vars — those remain
untouched and functional; sandbox VM integration is a separate future phase.

## Architecture

```
scripts/install_headscale.sh (one-time, sudo)
       │
       ├── installs headscale binary + systemd service (system-level)
       ├── writes /etc/headscale/config.yaml
       └── bootstraps 'mojo' namespace + preauth key
       ▼
Headscale server (127.0.0.1:8080, systemd: headscale.service)
       │
       ├── tailscale client (this machine) ──tailscale up──▶ joins tailnet
       │                                                      as node 1
       ▼
NetworkProvider ABC (app/services/provider_contracts.py)
       │
       └── HeadscaleNetworkProvider (app/scheduler/network_provider.py)
              ├── register(node)   → provisions join credential
              ├── deregister(node) → headscale nodes delete
              ├── list_nodes()     → headscale nodes list --output json
              └── health_check()   → surfaced via config(action="doctor_health")
```

## Components

| File | Role |
|------|------|
| `scripts/install_headscale.sh` | Headscale server install + systemd unit + bootstrap |
| `app/services/provider_contracts.py` | `NetworkProvider` ABC + `NetworkNode` dataclass + `resolve_network_provider()` |
| `app/scheduler/network_provider.py` | `HeadscaleNetworkProvider` — talks to the `headscale` CLI via subprocess |
| `config/network_provider.json` | Schema defaults (system layer, `enabled: false`) |
| `~/.memory/config/network_provider.json` | Real values (personal layer) |
| `app/mcp/core/tools.py` (`_execute_doctor_health`) | `network_provider` health check |
| `tests/unit/test_network_provider.py` | Unit tests (mocked subprocess — CLI parsing, fail-open behavior, provider resolution) |

## Setup

### 1. Install the Headscale server

```bash
sudo ./scripts/install_headscale.sh
```

This downloads the pinned Headscale release, installs it as a system
systemd service (`headscale.service`, separate from `mojoassistant.service`),
writes `/etc/headscale/config.yaml` (loopback-only listen address, `mojo.internal`
MagicDNS domain, sqlite backing store), creates the `mojo` namespace, and
prints a 24h preauth key for the next step.

**Requires sudo** — this installs a new system service and binds a port;
it is not something to automate unsupervised.

### 2. Join this machine to the tailnet

```bash
sudo apt install tailscale
sudo tailscale up --login-server=http://127.0.0.1:8080 --authkey=<preauth key from step 1>
tailscale status && tailscale ip -4
sudo headscale nodes list
```

Verify the tailnet IP is assigned and the node shows up in
`headscale nodes list` before relying on it from code.

### 3. Enable in MoJoAssistant config

Edit `~/.memory/config/network_provider.json` and set `"enabled": true`
(it ships disabled by default so `doctor_health` skips cleanly on any
install that hasn't done steps 1-2 yet).

### 4. Verify

```
config(action="doctor_health")
```
should show a `network_provider` check with `status: "pass"` and this
machine's node reporting online.

## Config reference (`network_provider.json`)

| Key | Meaning |
|---|---|
| `enabled` | Whether the doctor check and provider resolution are active |
| `provider` | Provider name (`"headscale"` — only one exists in Phase 1) |
| `server_url` | Headscale server address (default `http://127.0.0.1:8080`) |
| `magic_dns_domain` | Internal DNS suffix (default `mojo.internal`) |
| `headscale_user` | Headscale namespace/user for MoJo's nodes (default `mojo`) |
| `cli_path` | Path to the `headscale` binary (default just `headscale`, relies on PATH) |

## Troubleshooting

- **`systemctl status headscale` shows failed, `status=203/EXEC` in
  `journalctl -u headscale -n 50`** — the systemd unit's `ExecStart` points
  at a binary path that doesn't exist. Hit live 2026-07-23: the `.deb`
  package installs to `/usr/bin/headscale` (Debian convention), not
  `/usr/local/bin/headscale`. Fixed in the installer (resolves the path via
  `command -v headscale` instead of hardcoding it) — if you hit this on an
  already-installed unit, fix directly: `sudo sed -i 's|ExecStart=.*|ExecStart='"$(command -v headscale)"' serve|' /etc/systemd/system/headscale.service && sudo systemctl daemon-reload && sudo systemctl restart headscale`.
- **`systemctl status headscale` shows failed for other reasons** — check
  `journalctl -u headscale -n 50`. Other common causes: port 8080 already in
  use, or `/var/lib/headscale` permissions (should be owned by the
  `headscale` system user the installer creates).
- **`headscale nodes list` returns nothing after joining** — re-run
  `tailscale status` on the client; if it shows "Logged out" the preauth key
  may have expired (24h) — generate a new one: `sudo headscale preauthkeys create --user mojo --reusable --expiration 24h`.
- **`doctor_health`'s `network_provider` check stays `skip`** — check
  `~/.memory/config/network_provider.json` has `"enabled": true`; the check
  is designed to skip cleanly rather than fail when this hasn't been set up.
- **`HeadscaleNetworkProvider` returns empty node lists / health status `error`
  even though the service looks fine** — the provider talks to Headscale via
  the CLI binary on `PATH`, not HTTP; confirm `headscale` is actually
  reachable from the environment MoJoAssistant's systemd service runs under
  (a `--user` unit doesn't automatically inherit a root-installed binary's
  PATH in every distro's default systemd environment — verify with
  `systemctl --user show-environment` if this happens).

## Out of scope (future phase)

Rewiring `CubeSandboxBackend`/`get_opencode_url()` to route through this mesh
instead of the cloudflared tunnel at `sandbox-api.eclipsogate.org`. That
integration touches the sandbox VM template and cube-proxy configuration,
not just this repo — see `docs/architecture/CUBESANDBOX_SETUP.md` for the
current (untouched) setup this phase does not replace.
