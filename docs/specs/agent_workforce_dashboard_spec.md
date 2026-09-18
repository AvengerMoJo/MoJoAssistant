# Spec: Agent Workforce Dashboard + Daily Review Loop

**Date:** 2026-09-17
**Status:** Draft — for Paul (PM) to turn into an execution plan
**Depends on:** `docs/architecture/AGENT_BRIDGE.md`, `docs/architecture/AGENT_WORKFORCE.md`
**Scope:** `app/mcp/agent_bridge/*`, a new dashboard surface, `herdr` session listing, MoJoAssistant scheduler

## Problem

The third-party agent workforce (AgentBridge + `opencode serve` workers over
Tailscale) is real and running — one control-plane bridge (control-plane host, :8497),
one registered worker (`orgvm-memoria-hk001`), six working MCP tools
(`agent_servers`, `agent_status`, `agent_run`, `agent_reply`,
`agent_sessions`, `agent_close_session`). But it is invisible and manual:

1. **No place to see the fleet.** The only inventory is a hand-maintained
   markdown table in `AGENT_WORKFORCE.md`. Knowing which hosts exist, where
   they are, and whether they're healthy requires reading docs or calling
   `agent_servers`/`agent_status` one host at a time.
2. **No hardware/capability model.** The registry (`hosts: {name: {base_url,
   password}}`) has no concept of what a host is *for* — a host with a GPU
   for image/video generation and a CPU-only host doing text-only agent work
   look identical in the schema.
3. **No cost/tier model.** "Free tier (`big-pickle`)" vs. "paid subscription
   backend" is a real distinction the user tracks manually today; nothing
   in the registry or scheduler is aware of it.
4. **Three disconnected session views.** MCP clients see sessions through
   AgentBridge's `agent_sessions`. Humans see sessions through `herdr`.
   There is no single place a human reviewing the day's work can see
   "everything that happened" across MCP-driven, AI-driven (scheduler), and
   human-driven sessions.
5. **No repeatable daily loop.** The user wants to schedule real
   unattended work on the workforce and only be pulled in for one
   human-review checkpoint per day — that loop does not exist; today
   everything is invoked ad hoc.

## Desired Outcome

- A structured **host registry schema** that captures location, hardware
  profile, and cost tier per host — not just reachability.
- A **dashboard** (data + a view) that answers "what hosts exist, where,
  what can they do, what's running on them, what did today cost" without
  reading docs or making six tool calls.
- **One unified session list** spanning MCP-driven, scheduler-driven, and
  human (`herdr`) sessions, so a human reviewing the day sees everything in
  one place.
- A **daily automated loop**: the scheduler dispatches work to the
  workforce continuously, and pauses once a day at a single HITL checkpoint
  for a human review, rather than requiring supervision per task.

## Non-Goals

- Replacing `herdr` as the interactive human control surface — it stays;
  this only asks it to expose its session list to the unified view.
- A general-purpose cloud cost/billing system — tier is a coarse label
  (`free`, `subscription:<name>`), not a metered billing integration.
- Multi-tenancy / access control beyond what BasicAuth + tailnet binding
  already provides (see `AGENT_BRIDGE.md` security notes — unchanged).
- Changing the `opencode serve` worker protocol itself.

## Design

### 1. Registry schema extension

`~/.memory/config/agent_bridge.json`, `hosts.<name>` gains three new
optional objects (all optional so existing configs keep working
unmodified — `orgvm-memoria-hk001` today has none of these and must
continue to load):

```json
{
  "hosts": {
    "orgvm-memoria-hk001": {
      "base_url": "http://<worker-tailnet-ip>:4096",
      "password": "<OPENCODE_SERVER_PASSWORD>",
      "location": { "region": "hk", "provider": "orgvm", "note": "Hong Kong VPS" },
      "profile": {
        "hardware_accel": ["none"],
        "capabilities": ["text"]
      },
      "tier": { "type": "free", "backend": "big-pickle" }
    },
    "example-gpu-host": {
      "base_url": "http://100.x.y.z:4096",
      "password": "...",
      "location": { "region": "home", "provider": "self-hosted" },
      "profile": {
        "hardware_accel": ["nvidia-cuda"],
        "capabilities": ["text", "graphics", "audio-transcription"]
      },
      "tier": { "type": "subscription", "backend": "zai-coding-plan" }
    }
  }
}
```

- `location`: free-form but with `region`/`provider` as the two fields the
  dashboard sorts/groups by.
- `profile.hardware_accel`: enum-ish list — `none`, `nvidia-cuda`,
  `amd-rocm` (Linux ROCm), `amd-directml` (Windows AMD NPU/iGPU via
  DirectML — added after registering a Windows worker with an AMD
  Ryzen AI Max+ 395 chip, since ROCm's Windows support doesn't cover
  this path), `apple-mps`.
  Drives which hosts a graphics/audio-transcription task is eligible to
  land on.
- `profile.capabilities`: what kinds of work the host is fit for —
  `text`, `graphics`, `audio-transcription`, extend as needed.
- `tier.type`: `free` | `subscription` | `paid-api`. `tier.backend`: the
  concrete provider/plan name (`big-pickle`, `zai-coding-plan`, etc.) —
  mirrors the naming already used in
  `project_unified_provider_resource_pool_vision` so the two systems can
  be reconciled later without a rename.

**Files:** `app/mcp/agent_bridge/config.py` (loader — add optional-field
parsing, must not break configs lacking these keys),
`app/mcp/agent_bridge/registry.py` (`HostRegistry` — carry the new fields
through to whatever reads it), `config/agent_bridge.example.json` (update
example).

### 2. Dashboard

Two new AgentBridge MCP tools (same FastMCP server, same auth):

- `agent_fleet()` → returns every host's full registry entry (location,
  profile, tier) merged with live `agent_status` reachability, in one call.
  This is the data endpoint; a human-facing rendering is a thin client over
  it, not a new backend.
- `agent_fleet_summary()` → same data, grouped by `region` and `tier.type`,
  with per-group session counts (pulled from `agent_sessions` per host) —
  the "what's running and what's it costing" view.

Rendering: start as a CLI-friendly table (matches the project's existing
preference for `--json` scriptable output alongside human tables, see
`herdr <group> --json` in `AGENT_BRIDGE.md`) — a full web dashboard is
explicitly a stretch goal, not required for v1. Ship the data tools first;
Paul/implementers should treat a rendered UI as a fast-follow, not a
blocker.

**Files:** `app/mcp/agent_bridge/server.py` (new tool registrations),
`tests/unit/test_agent_bridge.py` (mock-backed tests for both new tools).

### 3. Unified session list (herdr integration)

`herdr agent list --json` (already documented in `AGENT_BRIDGE.md`) is the
human-surface session list today. Add one aggregation point rather than
merging the two systems:

- New tool `agent_sessions_unified(host?)` on the bridge: calls
  `agent_sessions` (MCP/AI-driven sessions) for the given host(s) **and**
  shells out to `herdr agent list --json` on that host over SSH (the
  bridge already has host SSH reachability via the managed-host backend;
  see `SSH_REMOTE_SANDBOX.md`), tags each session with its origin
  (`mcp`, `scheduler`, `human`), and returns one merged, time-sorted list.
- This is additive and read-only — it does not change herdr's own
  behavior or session model, it only reads from it.

**Files:** `app/mcp/agent_bridge/server.py` (new tool), a small
`herdr_client.py` helper if none exists for shelling out to `herdr --json`
over the managed SSH backend.

### 4. Daily automated loop with human review

Use the existing scheduler (`type: "scheduled"`, `cron`) — no new
scheduling engine needed:

- A new scheduled task type/goal template: dispatches queued/queued-up
  workforce work across eligible hosts (matched by `profile.capabilities`
  / `tier`) throughout the day via `agent_run`/`agent_reply`.
- At a fixed daily time, schedule one `internal_assignment` task (role:
  Paul, or a new lightweight "daily reviewer" role) whose goal is: call
  `agent_fleet_summary()` + `agent_sessions_unified()`, produce a short
  status digest (what ran, what's pending, any host degraded), and raise
  it via the existing HITL path (`ask_user` / HITL inbox) for the human's
  one-touch daily approval — exactly the "human in the between daily
  review status" the user asked for. This reuses BRIDLE's existing
  Act → Validate → Log → Dream → Learn → Correct loop rather than
  inventing a parallel review mechanism.

**Files:** a new scheduler goal/prompt template (location per existing
scheduler task conventions — see `app/scheduler/handlers/`), no core
scheduler code changes expected since `cron` + `internal_assignment` are
already supported task shapes.

## Acceptance Criteria

- [x] Existing `orgvm-memoria-hk001` config (no new fields) still loads
      and the bridge still starts — schema extension is additive-only.
      Verified live: it has zero new metadata fields and still appears
      correctly in `agent_fleet()`'s real output after the 2026-09-18
      bridge restart.
- [x] `agent_fleet()` and `agent_fleet_summary()` return correct merged
      data against at least two hosts — verified live against **three**:
      `orgvm-memoria-hk001` (no metadata), a Windows GPU worker (full
      metadata, `opencode_serve`), a legacy worker (full metadata, `backend:
      "legacy_mcp"` — a genuinely different wire protocol, not a stub).
      This exceeded the original "even a stub" bar with a real
      heterogeneous-backend case.
- [ ] `agent_sessions_unified()` returns sessions tagged with the correct
      origin for at least one MCP-driven and one herdr-driven session.
      **Not yet implemented** — this AC is still open.
- [ ] A scheduled daily task successfully reaches the HITL checkpoint
      (`ask_user`/HITL inbox) with a real digest, once, end-to-end.
      **Not yet implemented** — still open.
- [x] `tests/unit/test_agent_bridge.py` covers the new tools with mocked
      `OpenCodeClient`/httpx calls — 20/20 passing, including a
      legacy_mcp-backend fleet test and a mixed-backend summary test.
      (SSH-shell-out mocking for `agent_sessions_unified` is still
      pending since that tool isn't built yet.)
- [x] `docs/architecture/AGENT_WORKFORCE.md`'s "Current inventory" table
      and `AGENT_BRIDGE.md`'s config example are updated to reflect the
      new schema fields, plus `config/agent_bridge.example.json`.

**Remaining scope**: `agent_sessions_unified()` and the daily HITL-review
loop (design items 3 and 4) are not built. What shipped here is the
registry schema extension and the fleet dashboard itself (items 1 and 2),
covering the user's explicit "add the 3rd agent, reflect its virtual
interface, show availability of the whole workforce" ask.

## Delivery

Branch from `main` (per `Coding Agents Rules.md` git practices) as
`wip_agent_workforce_dashboard`. Implement using whichever mix of the
native assistant (interactive, this session) and the third-party agent
workforce (`orgvm-memoria-hk001-agent` via AgentBridge, or any other
registered host) makes sense per piece — this feature is itself a good
first real test of the workforce dispatching real implementation work on
itself. PR back to `AvengerMoJo/MoJoAssistant` against `main` when the
acceptance criteria above are met, with a summary of what ran on the
native assistant vs. the workforce.
