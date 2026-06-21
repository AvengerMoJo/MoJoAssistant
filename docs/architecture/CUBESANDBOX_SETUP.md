# CubeSandbox Coding Agent Setup

KVM/RustVMM microVM isolation for coding agents — replaces Docker sandboxes and
the coding-agent-mcp-tool submodule.

## Architecture

```
MoJoAssistant handler
       │
       ├── CubeSandboxClient.start()  → boots microVM (<60ms hot start)
       ├── CubeSandboxClient.upload_project() → copies files into VM
       ├── CubeSandboxClient.get_opencode_url() → proxied URL
       │
       ▼
  OpenCodeClient (httpx)  ←→  OpenCode server (inside VM, port 4173)
       │
       ├── create_session / send_message / get_messages
       ├── respond_to_permission (HITL)
       ├── list_questions / reply_to_question (Question API)
       └── subscribe_events (SSE stream for permissions + questions)
```

## Components

| File | Role |
|------|------|
| `app/scheduler/sandbox/cubesandbox_client.py` | CubeSandbox VM lifecycle: start/kill/pause/resume/upload |
| `app/scheduler/sandbox/opencode_client.py` | Direct OpenCode HTTP client (replaces coding-agent-mcp-tool) |
| `app/scheduler/handlers/coding_session_opencode.py` | Session handler — uses both clients |
| `docker/opencode-sandbox/Dockerfile` | OpenCode image for CubeSandbox template |
| `tests/unit/test_coding_session_opencode.py` | 15 tests covering full lifecycle |

## Setup

### 1. Install CubeSandbox server

Follow [CubeSandbox docs](https://github.com/tencentcloud/CubeSandbox). Requires:
- KVM-enabled host
- `cubemastercli` on PATH
- `CUBEMASTER_ADDR` env var pointing to the cluster

### 2. Install E2B SDK

```bash
pip install e2b
```

### 3. Build OpenCode template

```bash
# Build and push the image
docker build -t my-registry/opencode-sandbox:latest \
  -f docker/opencode-sandbox/Dockerfile .
docker push my-registry/opencode-sandbox:latest

# Register as CubeSandbox template
cubemastercli tpl create-from-image \
  --image my-registry/opencode-sandbox:latest \
  --writable-layer-size 2G \
  --expose-port 4173 \
  --probe 4173 \
  --probe-path /health

# Wait for template to be READY
cubemastercli tpl watch --job-id <job_id>

# Note the template_id
export CUBE_TEMPLATE_ID=tpl-xxxxxxxxxxxx
```

### 4. Configure MoJoAssistant

Add to `.env`:
```
E2B_API_URL=http://localhost:3000
E2B_API_KEY=your-cubesandbox-api-key
CUBE_TEMPLATE_ID=tpl-xxxxxxxxxxxx
```

### 5. Dispatch a coding session

```python
# Via MCP tool
external_agent(
    action="backend_session_run",
    prompt="Write a REST API in Go with JWT auth",
    backend_type="opencode",
    working_dir="/home/alex/projects/myapp"
)
```

The handler will:
1. Boot a CubeSandbox VM from the OpenCode template (<60ms)
2. Upload project files into the VM
3. Connect to OpenCode inside the VM via proxy URL
4. Send the prompt and manage the session lifecycle
5. Surface permission/question HITL through MoJo's existing inbox
6. Send completion notification when done

## Cost Evaluation

| Resource | Per session | Notes |
|----------|-------------|-------|
| VM boot | <60ms | Hot start from snapshot |
| Memory | <5MB per VM | Stripped kernel |
| Disk | 2GB writable layer | Copy-on-write from template |
| Isolation | Dedicated kernel | No shared-kernel escape |

## What Was Removed

- `coding-agent-mcp-tool` submodule dependency from the handler
- `BackendRegistry`, `OpenCodeBackend`, `ClaudeCodeBackend` imports
- `_get_backend()` method (replaced with `_get_client()`)

The handler now talks HTTP directly via `OpenCodeClient` — no submodule needed.

## Fallback: Direct OpenCode (no sandbox)

If CubeSandbox is unavailable, the handler falls back to connecting to OpenCode
directly:

```python
# Set use_sandbox=False or provide opencode_url in task config
task.config["use_sandbox"] = False
task.config["opencode_url"] = "http://localhost:4173"
```

Or leave `use_sandbox=True` — if CubeSandbox fails to start, the handler
catches the error and falls back to `http://localhost:4173` automatically.

## Current Local Setup Status (2026-06-21)

### What's live on this machine

| Component | Host port | Internal port | Status |
|-----------|-----------|---------------|--------|
| `cubemaster` (one-click) | 8089 | 8089 | ✅ HEALTHY |
| `cubelet` gRPC (one-click) | 9999 | 9999 | ✅ Node `192.168.2.248` RUNNING |
| `cube-api` (one-click) | 3000 | 3000 | ✅ up |
| `cube-webui` (one-click) | **12088** | 80 | ✅ up |
| `network-agent` (one-click) | **19090** | 19090 | ✅ up |
| `cube-proxy` (e2b API) | **12080 / 12443** | 80 / 443 | ⚠️ needs `sudo` to start |
| MySQL (one-click) | 3306 | 3306 | ✅ up |
| Redis (one-click) | 6379 | 6379 | ✅ up |
| `portainer_agent` (Docker) | 9001 | 9001 | ✅ up |
| `opencode-sandbox` template | — | — | ✅ READY (`tpl-674134307cfa458a986b05ab`) |

### Port scheme: 120XX convention

All CubeSandbox-related services bind to **120XX host ports** so they live in one memorable block. Default cube-proxy 80/443 was kept as container-internal — only the *host* port mapping is 12080/12443, which avoids clashing with the host's Nextcloud on 80/443.

### Cloudflared hostnames

`~/.cloudflared/config.yml` adds three new ingress entries:

| Hostname | → Host port | Purpose |
|----------|-------------|---------|
| `sandbox.eclipsogate.org` | 12443 (HTTPS, mkcert) | cube-proxy e2b-API |
| `dashboard.eclipsogate.org` | 12088 (HTTP) | cube-webui dashboard |
| `portainer.eclipsogate.org` | 9001 (HTTP) | portainer agent |

To switch the MoJo handler to the tunneled endpoint, set in `.env`:
```
E2B_API_URL=https://sandbox.eclipsogate.org
```

### To bring up cube-proxy (still needs sudo)

```bash
sudo CUBE_PROXY_HTTP_PORT=12080 \
     CUBE_PROXY_HTTPS_PORT=12443 \
     bash /usr/local/services/cubetoolbox/scripts/one-click/up-cube-proxy.sh
```

The script accepts these env vars natively (no config patch needed) and renders `nginx.conf` with the new listen ports. With `network_mode: host`, the container will then bind 12080/12443 directly on the host.

### `.env` additions for CubeSandbox

```
E2B_API_URL=http://127.0.0.1:12080          # local cube-proxy (or https://sandbox.eclipsogate.org)
E2B_API_KEY=local-dev-key                   # cube-proxy accepts any non-empty key
CUBE_TEMPLATE_ID=tpl-674134307cfa458a986b05ab
E2B_VALIDATE_API_KEY=false                  # disable e2b SDK key-format check
```

### What was done without sudo

- Built `opencode-sandbox:latest` Docker image
- Compiled `cubelet` binary from source (protoc + protoc-gen-go installed in `~/go/bin`)
- Patched `docker/opencode-sandbox/Dockerfile` (unzip, `opencode-ai` package, `/api/health` probe, `--hostname`)
- Updated `app/scheduler/sandbox/cubesandbox_client.py` health check to `/api/health`
- Added cloudflared ingress entries (3 new hostnames)
- Appended `E2B_*` and `CUBE_TEMPLATE_ID` to `.env`

### Blockers remaining

The one-click installer and cube-proxy startup both require `sudo` (touch `/etc/systemd`, mount XFS on `/data`, bind host ports <1024 are fine, but `docker compose build` and `nginx` exec need root). Until those run, the e2b SDK path is non-functional — the handler falls back to direct OpenCode on the host via the Phase-2 `OpenCodePerTaskBackend`.

```
~/.memory/sandboxes/cubesandbox/        # cloned source (prebuilt bin + Cubelet/)
~/.memory/cubemaster-config/
  ├── cubemaster.yaml                   # config with port overrides
  ├── start.sh                          # starts cubemaster daemon
  ├── cubelet.yaml                      # cubelet config (meta_server_endpoint)
  └── start-cubelet.sh                  # starts cubelet (hangs without root)
~/.memory/cubemaster-data/
  ├── log/CubeMaster/                   # cubemaster logs
  └── cubelet-stdout.log                # cubelet output (empty)
~/.memory/cubelet-data/                 # cubelet root (empty)
docker/opencode-sandbox/Dockerfile      # OpenCode 1.17.9 + bun + unzip
```
