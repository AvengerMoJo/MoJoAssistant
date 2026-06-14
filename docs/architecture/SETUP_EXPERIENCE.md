# MoJoAssistant Setup Experience — Implemented

## Goal

A new user runs one command and gets:
1. An honest report of what actually works in their environment
2. Guided setup for everything that doesn't
3. A clear stable vs experimental label on every feature

```
python3 scripts/doctor.py --setup
```

---

## Three Layers

### Layer 1 — Feature Validator (gate #6)

Live probes for each feature area. Not static docs — actual checks against the
running system.

```
MoJoAssistant Setup Check
═══════════════════════════════════════════════

Core (Stable)
  ✅ Scheduler daemon        — running, 3 tasks queued
  ✅ HITL inbox              — reachable, 0 pending
  ✅ Memory search           — local embeddings active (all-MiniLM-L6-v2)
  ✅ MCP tool surface        — 12 tools registered
  ✅ Policy checker          — active, 23 patterns loaded
  ✅ Role system             — 4 roles loaded
  ✅ Audit trail             — append-only log active

Optional (Experimental)
  ⚠️  Agent execution        — no LLM reachable at http://localhost:1234
  ⚠️  Coding agent bridge    — claude not found in PATH
  ❌  Voice pipeline         — mojo-voice not configured (see docs/guides/VOICE.md)
  ❌  CubeSandbox            — E2B_API_URL not set (run Ahman's install task first)

Run `python3 scripts/doctor.py --fix` to set up any ⚠️/❌ items interactively.
```

**Probe implementations** (one per feature area):
- Scheduler: `GET /api/health` → check `scheduler.status == "running"`
- Memory: instantiate `get_memory_provider()`, call `health_check()`
- MCP: count entries in `tool_catalog.json`
- Policy: check `behavioral_patterns.json` exists + pattern count
- Roles: count `~/.memory/roles/`
- Agent execution: HTTP probe to configured LLM endpoint
- Coding agent: `which claude && claude --version`
- Voice: check `mojo-voice` dir + `VOICE_ENABLED` in config
- CubeSandbox: check `E2B_API_URL` in env / `infra_context.json`

---

### Layer 2 — Interactive Setup Wizard (gate #7)

Triggered by `--fix` or automatically when a core item fails. Walks the user
through each broken item with exact commands to type.

#### Step 1 — Memory & MCP Server

```
─── Step 1: Memory & MCP Server ───────────────────────────────

MoJo's memory lives in ~/.memory/. The MCP server lets Claude
talk to MoJo's tools directly.

  Memory path:  ~/.memory/          [exists ✅]
  MCP server:   not running         [❌]

Start the MCP server?  [Y/n]: Y

  Starting MoJo as a systemd user service...
  $ systemctl --user enable mojoassistant
  $ systemctl --user start mojoassistant
  ✅ MCP server running on port 3100
```

#### Step 2 — Connect Claude

```
─── Step 2: Connect Claude to MoJo ────────────────────────────

How will you use Claude?

  1. Claude Code on this machine     (same computer, no tunnel needed)
  2. Claude.ai in browser            (needs cloudflared tunnel)
  3. Claude Code on another machine  (needs cloudflared or Tailscale)

Choice [1]: 2

  Setting up cloudflared tunnel...
  $ cloudflared tunnel --url http://localhost:3100

  Your MoJo MCP URL:  https://xxxxx.trycloudflare.com

  Add this to Claude.ai → Settings → Integrations:
    URL:  https://xxxxx.trycloudflare.com/mcp
    Name: MoJo

  Press Enter once you've added it...  ✅ Connected
```

#### Step 3 — LLM Backend (for agent execution)

```
─── Step 3: LLM Backend (for agent tasks) ─────────────────────

Agent execution lets roles run autonomous tasks using a local LLM.
This is EXPERIMENTAL — works best with Qwen2.5 via LMStudio.

  Detected LMStudio: not running
  Detected Ollama:   not running

  Options:
    1. LMStudio (recommended) — download at lmstudio.ai
    2. Ollama                 — run: curl -fsSL https://ollama.ai/install.sh | sh
    3. Skip for now           — roles can still chat, just no autonomous tasks

  Choice [3]: 3
  ⚠️  Agent execution marked experimental — skipped
```

#### Step 4 — Validate & Summary

```
─── Step 4: Validation ────────────────────────────────────────

Running stable smoke suite...

  ✅ Scheduler tick
  ✅ Memory read/write
  ✅ MCP tool surface (12 tools)
  ✅ Policy check
  ✅ HITL inbox

All stable checks passed.

─── Your MoJo is ready ────────────────────────────────────────

  Stable features (working now):
    • Memory search & storage
    • Role system (4 roles loaded)
    • HITL inbox & policy enforcement
    • MCP tools via Claude.ai

  Experimental features (need extra setup):
    • Agent execution    → install LMStudio + Qwen2.5
    • Voice pipeline     → see docs/guides/VOICE.md
    • CubeSandbox        → contact Ahman (infra role)

  Quick start:
    Chat with a role:   open Claude.ai → use MoJo integration
    Check tasks:        GET http://localhost:3100/api/health
    Restart MoJo:       systemctl --user restart mojoassistant
```

---

### Layer 3 — Pytest Stable/Experimental Markers (gate #5)

Every smoke test gets a marker. CI runs only `stable`. Users can run both.

```python
# tests/smoke/test_scheduler.py
@pytest.mark.stable
def test_scheduler_tick(): ...

# tests/smoke/test_agent_execution.py
@pytest.mark.experimental
def test_qwen_tool_call(): ...
```

```
# Clean install gate (CI):
pytest tests/smoke/ -m stable

# Full picture (user running --setup):
pytest tests/smoke/ -m stable    → must all pass
pytest tests/smoke/ -m experimental --no-header  → shown as "what needs extra setup"
```

---

## Connectivity Options — Detail

### Option 1: Local only
Claude Code on the same machine. Zero config beyond starting MoJo.
```json
// ~/.claude/mcp_servers.json
{
  "mojoassistant": {
    "url": "http://localhost:3100/mcp"
  }
}
```

### Option 2: Cloudflared tunnel
Exposes MoJo to Claude.ai or remote Claude Code. Ephemeral URL — changes on
restart unless you configure a named tunnel.
```bash
# One-shot (URL changes each run):
cloudflared tunnel --url http://localhost:3100

# Persistent (recommended):
cloudflared tunnel create mojo
cloudflared tunnel route dns mojo mojo.yourdomain.com
cloudflared tunnel run mojo
```
Run as systemd service so it starts with MoJo.

### Option 3: Tailscale / Headscale (post-beta)
Self-hosted mesh VPN — stable internal hostname across all your devices.
Deferred to post-v2.0.0. See memory: `project_network_provider_vision.md`.

---

## Implementation Plan

### Phase A — Stable/Experimental markers (2–3 hours)
1. Add `pytest.ini` markers: `stable`, `experimental`
2. Tag all existing smoke tests
3. Update CI to run `pytest tests/smoke/ -m stable`
4. Document in `INSTALL.md`

### Phase B — Feature validator (1 day)
1. Add `--setup` / `--fix` flags to `scripts/config_doctor.py`
2. Implement probes per feature area (list above)
3. Human-readable output (not raw JSON)

### Phase C — Interactive wizard (1–2 days)
1. MCP server start (systemd wiring)
2. Connectivity choice + cloudflared config generation
3. LLM backend detection
4. Final smoke run + summary

### Phase D — Stable/experimental surface doc (2 hours)
1. Add feature table to `INSTALL.md`
2. Cross-reference from README

---

## Acceptance Criteria for v1.4.1

- [ ] `python3 scripts/doctor.py --setup` runs end-to-end on a clean machine
- [ ] Every smoke test is marked `stable` or `experimental`
- [ ] `pytest tests/smoke/ -m stable` passes with 0 failures on a clean install
- [ ] Cloudflared tunnel option generates working `mcp_servers.json`
- [ ] Feature table in `INSTALL.md` matches live probe results
- [ ] No LLM or API key required for stable checks to pass
