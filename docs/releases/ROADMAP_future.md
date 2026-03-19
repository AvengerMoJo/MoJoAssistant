# MoJoAssistant Future Roadmap

## Direction

MoJoAssistant is building toward a **local-first privacy proxy** — a trusted
intermediary where a local thinking LLM processes sensitive data before it
touches any external service. Each release adds one layer of that architecture.

```
User / External World
        ↕  (controlled, audited, sanitized)
  MoJoAssistant Gateway
        ↕  (local only, never leaves device)
  Local LLM + Memory + Tools
```

---

## v1.2.0-beta (shipped)
Role safety, HITL, extensible tools, config validation, smoke test.
Foundation layer — the infrastructure exists, guardrails are opt-in.

## v1.2.1-beta (current)
Attention Layer + MCP consolidation + scheduler improvements.
- AttentionClassifier + EventLog hitl_level at every event write
- Wake-up hook in `get_context()` — LLM wakes aware, not blind
- 49 tools → 12 visible (5 top-level + 7 action hubs)
- `get_context` unified read (replaces 4 separate tools)
- Scheduler wake signal (zero-latency task dispatch)
- Config-driven default tasks (`scheduler_config.json`)
- SSE standard event envelope

## v1.2.2-beta (next)
Per-source attention routing rules — config-driven escalation levels
so security failures surface higher than dreaming failures.
See "Per-Source Routing Rules" below.

---

## Future Releases

### Data Boundary Enforcement

**Problem:** Nothing prevents data from a "local only" task from flowing into
an external LLM call in a subsequent step. Policy blocks tools, not data flows.

**Design:**
- `"local_only": true` flag on tasks and roles
- Executor refuses to route any data from a `local_only` session to a resource
  with `type != "local"` or `tier != "free"`
- Violation → task fails with clear error, not silent data leak

**Files:** `agentic_executor.py`, `models.py`, `role_manager.py`

---

### Audit Trail — Data Boundary Crossings

**Problem:** No way to answer "did any of this conversation touch an external API?"

**Design:**
- Every resource call logged with: task_id, resource_id, resource_type (local/api),
  timestamp, token count (no content)
- New MCP tool `audit_get_crossings(task_id)` — shows exactly which external
  resources a task touched and when
- Stored in `~/.memory/audit_log.json` (separate from event log, never purged)

**Files:** `agentic_executor.py`, new `app/mcp/adapters/audit_log.py`, `tools.py`

---

### PII / Data Classification Layer

**Problem:** The system has no concept of sensitive data. A local LLM might
extract PII and pass it to an external tool without any warning.

**Design:**
- `DataClassifier` — lightweight pattern-based scanner (regex + local model)
  that runs on tool inputs/outputs and flags: PII, credentials, financial data,
  health data
- Classification result attached to the session context
- If classified data is about to cross a boundary → warn or block depending
  on role policy (`"block_pii_external": true`)
- Not a replacement for careful design — a safety net

**Files:** New `app/security/data_classifier.py`, `agentic_executor.py`

---

### Sanitization Layer

**Problem:** Before a locally-processed result goes to an external service,
nothing strips or abstracts the sensitive parts.

**Design:**
- `DataSanitizer` — transforms data before it crosses the local boundary
- Strategies: redact (replace PII with `[REDACTED]`), abstract (replace specific
  values with category labels), summarise (local LLM rewrites without specifics)
- Configured per role: `"external_sanitization": "redact"` or `"abstract"`
- Applied automatically when a local result is passed to an external resource

**Files:** New `app/security/sanitizer.py`, `agentic_executor.py`, `role_manager.py`

---

### Per-Source Routing Rules (Attention Layer extension)

**Problem:** All opencode results land at the same attention level. All failures
look the same. Source-aware routing would let security failures escalate higher
than dreaming failures.

**Design:** Extend `AttentionClassifier` with a config-driven rule layer:
```json
{
  "attention_rules": [
    {"source": "ahman", "event_type": "task_failed", "hitl_level": 4},
    {"source": "opencode", "event_type": "task_completed", "hitl_level": 1},
    {"severity": "error", "source_tag": "security", "hitl_level": 5}
  ]
}
```
Rules evaluated before defaults. Configurable via `config` MCP tool.

**Files:** `attention_classifier.py`, `config/attention_config.json`

---

### Infrastructure Routing (Long-term)

**Problem:** High-priority events (level 4–5) should reach the user even when
no MCP client is open — not just via ntfy push.

**Design:**
- Level 3–4 → existing ntfy push (already works)
- Level 5 → terminal bell / system notification in active SSH session
- Level 0–2 → daily digest written to `~/.memory/digest/YYYY-MM-DD.md`
- Digest MCP tool: `get_daily_digest(date)` — human-readable summary of the day

**Files:** New `app/mcp/adapters/push/terminal.py`, new digest writer in scheduler

---

---

### Policy Enforcement Agent

**Problem:** `denied_tools` and `allowed_tools` are static setup-time rules.
They can't understand context — they block or allow regardless of what data
is actually flowing or what the operation will do.

**Design:**
- A `PolicyAgent` role that subscribes to the inbox event stream
- Receives events *before* operations complete — not just logs them after
- Classifies events using DataClassifier (PII, credentials, boundary crossings)
- Decisions: ALLOW (record + proceed), BLOCK (cancel + escalate to hitl_level 5)
- Every decision written to the audit log with reasoning
- Configurable per role: `"policy_agent": "strict"` or `"permissive"`
- Works in concert with the Sanitization Layer — PolicyAgent can trigger
  sanitization instead of outright blocking when data can be cleaned

**Why the inbox enables this:**
All inter-agent communication, external calls, and HITL questions flow through
the event stream. The inbox is the natural interception point — the PolicyAgent
reads events before they are acted on, not after.

**Files:** New `app/scheduler/policy_agent.py`, `app/mcp/adapters/event_log.py`
(pre-execution hooks), `app/config/doctor.py` (validate policy_agent config)

---

### Message Passing + Containerized Components

**Problem:** All components (MCP server, scheduler, agents) live in one Python
process, communicating via in-process method calls. This means one component
crashing affects all others, scaling requires forking the entire process, and
agents must be written in Python.

**Design:**
- Replace in-process method calls with explicit message passing through
  the existing `EventLog` + SSE bus
- Define a typed message envelope: `source`, `destination`, `message_type`,
  `payload`, `reply_to` — same schema as today's events, made explicit
- Each component (MCP server, scheduler, each agent role) becomes an
  independent process/container that sends and receives typed messages
- `reply_to_task` already defines the reply message schema — it works
  identically over a network bus
- Migration path: gradual. In-process calls remain as fallback;
  message bus becomes primary; containers become optional at any step

**Near-term (no containers required):**
- Multi-process: scheduler as a separate daemon (already partially true)
- Agent isolation: each role's task runs in a subprocess with message-only I/O
- Language-agnostic: a Rust or Go component can join the bus

**Long-term:**
- Full containerization: Docker/OCI containers per component
- The message bus (EventLog → Redis/NATS) is the only shared surface
- Policy Agent as a sidecar container inspecting all messages

**Files:** `app/mcp/adapters/event_log.py` (message bus extension),
new `app/messaging/` module, `app/scheduler/core.py` (subprocess boundary)

---

### Inbox → Dreaming → Institutional Knowledge

**Problem:** When an assistant and a 3rd-party agent resolve a problem via
the HITL inbox (question → context → answer → task completed), that entire
interaction is structured knowledge. Today it dissolves into raw conversation
text and loses its typed structure before dreaming can see it.

**Design:**
- New dreaming pipeline stage: **Inbox Distillation**
- Runs after nightly dreaming on the previous day's EventLog slice
- Pairs `task_waiting_for_input` + `task_completed` events by `task_id`
- Extracts: role, problem stated, context at the time, resolution provided,
  outcome (success/failure), iteration count
- Produces a structured "resolved interaction" knowledge unit:

```json
{
  "type": "resolved_interaction",
  "role": "ahman",
  "problem": "which subnet should I scan?",
  "context_summary": "weekly security review, home network setup",
  "resolution": "scan 10.0.0.0/24",
  "outcome": "completed — found 3 open ports, no critical issues",
  "resolved_by": "user_reply",
  "task_id": "ahman_scan_001",
  "refined_at": "2026-03-20T03:00:00"
}
```

- Stored in archival memory — surfaces automatically via `search_memory()`
- Over time: the assistant builds institutional knowledge about how problems
  are resolved, by whom, and with what outcome
- The dreaming LLM can also identify *patterns* across interactions:
  "Ahman always needs subnet clarification on home network tasks"
  → becomes a role-level hint injected into future Ahman task prompts

**Files:** New `app/dreaming/inbox_distillation.py`,
`app/dreaming/pipeline.py` (add optional inbox stage),
`app/mcp/adapters/event_log.py` (expose filtered slice for dreaming)

---

## Summary Table

| Feature | Protects / Enables | Scope |
|---------|---------|-------|
| Per-source routing rules | Attention quality | v1.2.2 |
| Data boundary enforcement | Data flows | v1.3.x |
| Audit trail | Accountability | v1.3.x |
| PII classification | Sensitive data leakage | v1.3.x |
| Sanitization layer | External exposure | v1.3.x |
| Infrastructure routing | Reachability | v1.3.x |
| Policy Enforcement Agent | Proactive blocking, context-aware safety | v1.4+ |
| Message passing + containerization | Fault isolation, language agnosticism, scale | v2.x |
| Inbox → Dreaming → Knowledge | Institutional memory, pattern learning | v1.4+ |
