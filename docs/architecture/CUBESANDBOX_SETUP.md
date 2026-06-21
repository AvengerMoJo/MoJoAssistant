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

### ✅ End-to-end verified working

```python
import os, e2b
sb = e2b.Sandbox.create(template=os.environ['CUBE_TEMPLATE_ID'])
# OK sandbox_id = 8fad30160801419a984f7ddb8aa49049
host = sb.get_host(4173)
# Host: 4173-8fad30160801419a984f7ddb8aa49049.eclipsogate.org

import httpx
httpx.get(f'http://{host}/api/health', timeout=10)
# HTTP 200 {"healthy":true}
```

### Live component layout

| Component | Host port | Container port | Status |
|-----------|-----------|----------------|--------|
| `cubemaster` (one-click) | 8089 | 8089 | ✅ HEALTHY |
| `cubelet` gRPC | 9999 | 9999 | ✅ Node `192.168.2.248` RUNNING |
| `cube-api` (e2b gateway) | **12300** | 3000 | ✅ up |
| `cube-webui` dashboard | **12088** | 80 | ✅ up |
| `cube-proxy` HTTP | **12080** | 80 | ✅ up |
| `cube-proxy` HTTPS | **12443** | 443 | ✅ up |
| `network-agent` | 19090 | 19090 | ✅ up |
| MySQL (one-click) | 3306 | 3306 | ✅ up |
| Redis (docker, pwd `ceuhvu123`) | 16379 | 6379 | ✅ up |
| `portainer_agent` | 9001 | 9001 | ✅ up |
| `opencode-sandbox` template | — | — | ✅ READY (`tpl-674134307cfa458a986b05ab`) |

### Cloudflared hostnames (agent-owned overlay)

`docs/infra/cloudflared-cubesandbox.yml` (merged into `~/.cloudflared/config.yml`):

| Hostname | → Host port | Purpose |
|----------|-------------|---------|
| `sandbox-api.eclipsogate.org` | 12300 (HTTP) | **cube-api** — POST /sandboxes |
| `dashboard.eclipsogate.org` | 12088 (HTTP) | cube-webui |
| `sandbox.eclipsogate.org` | 12443 (HTTPS) | cube-proxy (direct access) |
| `*.eclipsogate.org` (wildcard) | 12443 (HTTPS) | cube-proxy handles `<port>-<sandbox_id>.eclipsogate.org` |

### To bring up the stack after reboot (sudo required)

```bash
# Persisted in /usr/local/services/cubetoolbox/.one-click.env so this survives reboots:
#   CUBE_PROXY_HTTP_PORT=12080
#   CUBE_PROXY_HTTPS_PORT=12443
#   CUBE_PROXY_REDIS_IP=127.0.0.1
#   CUBE_PROXY_REDIS_PORT=16379
#   CUBE_PROXY_REDIS_PASSWORD=ceuhvu123

sudo bash /usr/local/services/cubetoolbox/scripts/one-click/up-cube-proxy.sh
sudo CUBE_API_BIND=0.0.0.0:12300 CUBE_API_SANDBOX_DOMAIN=eclipsogate.org \
     bash /usr/local/services/cubetoolbox/scripts/systemd/cube-api-start.sh

# Cloudflared (user-level):
pkill -f 'cloudflared tunnel'
nohup cloudflared tunnel --config /home/alex/.cloudflared/config.yml \
     run c7a1ca2b-c1ea-407d-8078-bdb65412f693 > /tmp/cloudflared.log 2>&1 &
```

### Why each env var matters

| Var | Why |
|-----|-----|
| `CUBE_PROXY_HTTP_PORT=12080` | Avoids Nextcloud on host 80/443 |
| `CUBE_PROXY_REDIS_PORT=16379` | cube-proxy's default (6379) points at one-click Redis (no password); docker Redis on 16379 has `ceuhvu123` which matches `redis_pd` |
| `CUBE_API_BIND=0.0.0.0:12300` | 120XX scheme |
| `CUBE_API_SANDBOX_DOMAIN=eclipsogate.org` | Makes SDK receive `<port>-<id>.eclipsogate.org`; requires `*.eclipsogate.org` wildcard DNS to be reachable |

### Critical bugs found during integration

1. **`sudo` strips env vars** — write port overrides to `/usr/local/services/cubetoolbox/.one-click.env`, not inline.
2. **Redis password mismatch** — cube-proxy defaults to one-click Redis (no password) but config has `ceuhvu123`. Fix via `CUBE_PROXY_REDIS_*` env vars.
3. **No `*.eclipsogate.org` wildcard DNS** — SDK can't reach per-sandbox URLs without it. `cloudflared tunnel route dns ... '*.eclipsogate.org'`.
4. **cube-proxy doesn't implement `POST /sandboxes`** — only forwards to *existing* sandboxes via the `<port>-<id>` Host regex. The create flow goes through **cube-api**.

### `.env` additions for CubeSandbox

```
E2B_API_URL=https://sandbox-api.eclipsogate.org
E2B_API_KEY=local-dev-key
CUBE_TEMPLATE_ID=tpl-674134307cfa458a986b05ab
E2B_VALIDATE_API_KEY=false
```

### Agent-owned files

- `docs/infra/cloudflared-cubesandbox.yml` — ingress overlay (4 entries)
- `scripts/merge_cloudflared_config.py` — merges overlay into `~/.cloudflared/config.yml`
- `tests/unit/test_cloudflared_merge.py` — 6 tests for the merge
- `app/scheduler/sandbox/cubesandbox_client.py` — uses e2b SDK with `/api/health` probe

### Files created for the partial setup

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
