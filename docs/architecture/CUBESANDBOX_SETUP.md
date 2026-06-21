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

What's running on this machine:

| Component | Status | Notes |
|-----------|--------|-------|
| Docker MySQL (cube-mysql) | running | port 33060 → 3306, db `cube_mvp` |
| Docker Redis (cube-redis) | running | port 16379 → 6379, pwd `ceuhvu123` |
| `cubemaster` daemon | running | port 8089, config at `~/.memory/cubemaster-config/cubemaster.yaml` |
| `cubemastercli` | ready | `~/.memory/sandboxes/cubesandbox/CubeMaster/build/` |
| `opencode-sandbox` Docker image | built | `opencode-sandbox:latest`, exposes 4173 |
| `cubelet` binary | built from source | protoc + protoc-gen-go installed under `/home/alex/go/bin` |

### Blockers preventing end-to-end CubeSandbox VM creation

The following **cannot be completed without `sudo`**:

1. **Cubelet boot hangs at startup.** It opens no sockets to `cubemaster`,
   no containerd connection, and produces no log output. Likely missing:
   - `/etc/containerd/config.toml` (permission denied to create)
   - CNI plugins at `/opt/cni/bin`, `/etc/cni/net.d`
   - Kernel artifacts under `/data/CubeMaster/...`
   - `XDG_RUNTIME_DIR` and other containerd runtime paths
2. **CubeSandbox is e2b-API incompatible out of the box.** The e2b SDK calls
   `POST /sandboxes`, but cubemaster's actual route is `/cube/sandbox` (POST).
   Adapting requires either:
   - **CubeProxy** (OpenResty/Lua nginx) — needs sudo to install
   - A custom adapter in `app/scheduler/sandbox/cubesandbox_client.py`
3. **The official `online-install.sh` script needs root** (creates
   `/usr/local/services/cubetoolbox`, `/var/run/cube-sandbox-one-click`,
   `/var/log/cube-sandbox-one-click`).

### What works today without CubeSandbox

The Phase-2 `OpenCodePerTaskBackend` already provides **per-task OpenCode
isolation** on the host: each coding session gets its own `opencode serve`
process on a unique port (e.g. 4101), with CWD scoped to the project
directory. This is the fallback path used by the handler today.

To switch back to direct OpenCode mode in production:

```python
# In the coding session task config
task.config["use_sandbox"] = False
```

The next session will start a fresh `opencode serve` process and run the
session against it — same HITL, same questions, same notification flow.

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
