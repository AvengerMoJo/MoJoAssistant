# MoJoAssistant — System Requirements & Resource Profile

*Last measured: 2026-04-08 on production host*

---

## Host Hardware (Reference System)

| Component | Spec |
|-----------|------|
| CPU | AMD Ryzen AI MAX+ 395 (32 cores) |
| RAM | 32 GB |
| Swap | 139 GB (NVMe-backed) |
| Disk | 3.5 TB NVMe (795 GB used) |
| GPU | Radeon 8060S (integrated, used by LMStudio) |

---

## MoJoAssistant Process

| Metric | Observed |
|--------|----------|
| Process | `python3 unified_mcp_server.py --mode http --port 8000` |
| RAM (RSS) | ~4.1 GB (13.5% of 30 GB) |
| CPU (idle) | ~1% |
| CPU (active task) | 1–5% (async I/O bound) |
| Port | 8000 (HTTP, MCP) |
| Python | 3.12 |

### What lives in that 4.1 GB

- FastAPI + Uvicorn async server
- All role JSON configs loaded into memory
- `scheduler_tasks.json` (2 MB) fully loaded
- `events.json` (218 KB) event log
- Embedding model (sentence-transformers, ~500 MB)
- Tool registry + dynamic tool catalog
- MCP client sessions (Playwright MCP, etc.)
- Session storage cache

---

## LMStudio (Local LLM backend)

| Metric | Observed |
|--------|----------|
| RAM (RSS) | ~5 GB (workers + UI) |
| Port | 8080 (OpenAI-compatible API) |
| Models in use | Qwen3.5-35B-A3B (primary), Gemma 4 27B |
| GPU VRAM | Used for inference (Radeon 8060S, shared memory) |

---

## Total RAM Pressure

| Component | RAM |
|-----------|-----|
| MoJoAssistant MCP server | ~4.1 GB |
| LMStudio (workers + UI) | ~5.0 GB |
| OpenCode (multiple instances) | ~0.9 GB |
| Other Python services | ~0.4 GB |
| OS + buffers/cache | ~2.7 GB |
| **Total used** | **~29 GB / 32 GB** |
| **Free (available)** | **~1.9 GB** |
| **Swap in use** | **~19 GB** |

**The system is RAM-constrained.** Only ~1.9 GB headroom before spilling further
into swap. Large model inference already causes swap pressure.

---

## Memory System (Disk)

Location: `~/.memory/`

| Path | Size | Notes |
|------|------|-------|
| `~/.memory/` (total) | 158 MB | |
| `task_sessions/` | 16 MB | Growing ~1 MB/week |
| `dreams/` | 18 MB | 100+ conversation archives |
| `roles/` | 4.9 MB | Role configs + knowledge units |
| `task_reports/` | 252 KB | v1 reports (v2 will grow this) |
| `config/` | 44 KB | Stable |
| `conversations_multi_model.json` | **57 MB** | ⚠ Largest single file — raw conversation log, unbounded growth |
| `scheduler_tasks.json` | 2 MB | All tasks ever run |
| `knowledge_multi_model.json` | 9.4 MB | Legacy global knowledge store |

### Growth projection

At current task volume (~5 tasks/day):
- `task_sessions/`: +~60 MB/month
- `scheduler_tasks.json`: +~0.5 MB/month
- `dreams/`: +~5 MB/month
- `conversations_multi_model.json`: **unbounded** — needs periodic archiving

---

## Minimum Requirements (to run MoJoAssistant without a local LLM)

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 2 GB | 4 GB |
| CPU | 2 cores | 4 cores |
| Disk | 10 GB | 50 GB |
| Python | 3.10+ | 3.12 |
| Network | Required for external API resources | — |

MoJoAssistant itself (without LMStudio) uses ~4 GB RAM. If using only
external API resources (OpenRouter, Claude API), **no GPU required**.

---

## Requirements to run a local LLM (LMStudio)

| Resource | Qwen3.5-35B (Q4) | Gemma 4 27B (Q4) |
|----------|-------------------|-------------------|
| RAM + VRAM | ~20 GB | ~16 GB |
| Disk | ~22 GB | ~18 GB |
| GPU | Recommended (10+ GB VRAM) | Recommended |
| CPU fallback | Possible but slow (>5 min/response) | Possible but slow |

On the reference system (Radeon 8060S, shared memory), Qwen3.5-35B
responds in 7–60 seconds depending on context size.

---

## Known Resource Issues

### 1. RAM headroom is tight
With LMStudio loaded, only ~1.9 GB remains before swap is hit. Adding
browser automation (Playwright MCP) or large model contexts pushes into
swap, causing latency spikes.

**Mitigation**: Playwright MCP is started on-demand (stdio transport),
not persistently. `max_concurrent` tasks = 3 limits parallel LLM calls.

### 2. `conversations_multi_model.json` grows unboundedly
At 57 MB it's the largest file in `~/.memory/`. It's loaded or scanned on
memory searches. No archiving or rotation exists today.

**Recommended fix**: Periodic archival to `~/.memory/archival/` after N
conversations or size threshold. Target for v1.3.x.

### 3. `scheduler_tasks.json` accumulates all task history
All completed/failed tasks stay in the file indefinitely. `scheduler purge`
helps but is not automated.

**Recommended fix**: Auto-purge completed tasks older than 30 days on
scheduler startup. Config flag: `auto_purge_after_days`.

### 4. Embedding model always loaded
The sentence-transformers embedding model (~500 MB) is loaded at startup
even if memory search is not used. Could be lazy-loaded.

---

## MCP Transport

| Mode | Port | Use case |
|------|------|----------|
| HTTP (production) | 8000 | Claude Code, ChatMCP, web dashboard |
| stdio | — | Direct subprocess embedding |

Authentication: JWT Bearer token (`~/.memory/jwt.txt`).

---

## External MCP Servers

| Server | Transport | Port | Notes |
|--------|-----------|------|-------|
| Playwright MCP | stdio | — | Spawned on-demand for browser tasks |
| LMStudio API | HTTP | 8080 | Local LLM backend |
| ntfy (notifications) | HTTP | 2586 | Self-hosted on MoJoAI (192.168.2.248) |

---

## Scheduler Concurrency Limits

| Limit | Value | Configured in |
|-------|-------|---------------|
| `max_concurrent` tasks | 3 | `scheduler_config.json` |
| Task wall-clock timeout (default) | 1800s (30 min) | `core.py` |
| LLM call timeout | 300s (read) / 10s (connect) | `unified_client.py` |
| MCP tool call timeout | 300s | `mcp_client_manager.py` |
| Per-tool output cap | 4000 chars | `agentic_executor.py` |
