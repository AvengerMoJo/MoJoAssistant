# Security Behavioral Monitor + Containment Engine

**Status:** Planned — v1.3.x
**Trigger:** Trivy supply chain attack (March 2026) + growing autonomous AI agent landscape
**Design date:** 2026-03-26

---

## The Problem This Solves

Inline policy checkers (v1.2.6) protect against **known bad** — tools on a blocklist,
tiers outside declared boundaries, violation counts exceeding limits. They are
synchronous, rule-based, and the agent is aware they exist.

They do not protect against **trusted-but-compromised** — the Trivy attack class:
a tool the system trusts, using allowed mechanisms, but doing something outside
its declared purpose. A compromised agent that passes every policy check because
it's using allowed tools for subtly wrong reasons sails through Layer 1.

In a world where AI agents run autonomously everywhere and humans can't audit
every log in real time, the dominant attack surface is not "bad software" — it's
"trusted software behaving outside its declared scope." This design addresses that.

---

## Three-Layer Security Model

```
AgenticExecutor
    │
    ├── [Layer 1] PolicyMonitor.check() ──────── inline, synchronous, blocking
    │       StaticChecker → ContentChecker       agent is aware of this layer
    │       → DataBoundaryChecker → ContextChecker
    │
    ├── [Layer 2] BehavioralMonitor.observe() ── parallel, non-blocking, silent
    │       Records everything, builds baseline   agent has NO awareness
    │       Scores anomalies, signals Layer 3
    │
    └── [Layer 3] ContainmentEngine.respond() ── triggered by Layer 2
            LOW   → silent ntfy warning, agent continues
            MED   → redirect to SandboxRuntime (honeypot)
            HIGH  → hard halt + HITL level 5 alert
```

Layer 1 is the gate. Layer 2 is the observer. Layer 3 is the trap.

The key architectural principle: **Layer 2 and Layer 3 are invisible to the agent.**
When containment activates, the agent believes it is running normally. This is
intentional — premature blocking reveals detection, allowing an attacker to adapt.
Silent containment lets the attack play out in a controlled environment while
intelligence is gathered.

---

## Layer 2: BehavioralMonitor

### Role

A parallel co-process that observes every tool call made by `AgenticExecutor`
without blocking or modifying execution. It maintains per-role behavioral profiles
and scores each session against them in real time.

### Behavioral Baseline (per role)

Over time, each role builds a profile of normal behavior:

```json
{
  "role_id": "researcher",
  "baseline": {
    "typical_tools": ["search_memory", "web_search", "ask_user"],
    "typical_call_count_per_session": {"mean": 8, "stddev": 3},
    "credential_path_access_rate": 0.0,
    "external_network_rate": 0.4,
    "bash_exec_rate": 0.05,
    "sessions_observed": 47
  }
}
```

Baseline is updated after each completed session using exponential moving average —
it adapts to role evolution without requiring manual reconfiguration.

### Suspicion Scoring

Each tool call is scored against the baseline. Signals that raise suspicion:

| Signal | Description | Weight |
|--------|-------------|--------|
| Credential path access | Tool args contain `~/.ssh/`, `~/.kube/`, `*_SECRET`, `*_TOKEN`, `docker/config.json`, AWS/GCP/Azure credential paths | HIGH |
| Scope drift | Role declared as `researcher` calling `bash_exec` on system paths | HIGH |
| Exfiltration chain | Encrypted content + external network call in same session window | CRITICAL |
| Volume anomaly | Call count > 3σ above role baseline | MEDIUM |
| Timing anomaly | Call frequency significantly faster than human-paced sessions | MEDIUM |
| Unusual tool combination | Tools not previously seen together for this role | LOW |
| Known C2 patterns | URLs matching typosquatted domains, suspicious TLDs in tool args | CRITICAL |

Suspicion score is cumulative within a session and decays slowly across sessions.
A single unusual action is noise. A pattern is signal.

### Anomaly Pattern File (`config/behavioral_patterns.json`)

```json
{
  "credential_paths": [
    "\\.ssh/id_",
    "\\.kube/config",
    "docker/config\\.json",
    "\\.aws/credentials",
    "\\.gcp/",
    "[A-Z_]+(SECRET|TOKEN|KEY|PASSWORD|CREDENTIAL)[A-Z_]*"
  ],
  "exfiltration_indicators": [
    "AES|RSA|encrypt",
    "base64.*upload|upload.*base64",
    "curl.*-d.*@",
    "wget.*--post"
  ],
  "c2_patterns": [
    "\\.(xyz|tk|ml|ga|cf)(/|$)",
    "typosquat detection via edit-distance against known registries"
  ]
}
```

---

## Layer 3: ContainmentEngine

### Thresholds and Responses

| Suspicion Level | Score | Response | Agent Awareness |
|----------------|-------|----------|-----------------|
| LOW | 30–60 | Silent ntfy push to user (level 2). Agent continues. Session flagged in EventLog. | None |
| MEDIUM | 60–85 | Redirect to SandboxRuntime. Agent continues "normally". User notified silently (level 3). | None |
| HIGH | 85+ | Hard halt. Task marked `suspended`. HITL level 5 alert. Full session log preserved for forensics. | Yes — task stops |

### SandboxRuntime

When containment activates at MEDIUM threshold, `AgenticExecutor` transparently
swaps its tool execution backend for `SandboxRuntime`. The agent calls tools with
the same interface and receives plausible responses — but nothing executes against
real resources.

**What gets sandboxed:**

| Real Tool | Sandbox Behavior |
|-----------|-----------------|
| `bash_exec` | Commands run in isolated container (Docker/bubblewrap). Output is real but filesystem is ephemeral, network is proxied. |
| File read/write | Redirected to a fake filesystem overlay. Real files appear readable (to maintain believability) but writes go to `/tmp/mojo-sandbox-{task_id}/`. |
| Network calls | Routed through a transparent monitoring proxy. External calls are logged and optionally blocked at the proxy level. |
| MCP tools | Real responses for read operations; write/mutate operations silently no-op with plausible success responses. |

**Honeypot intelligence gathering:**

While the agent runs in the sandbox, the ContainmentEngine records:
- Every tool call with full args (not just metadata)
- The exact credential paths being targeted
- Network destinations being contacted
- Data being assembled or encrypted
- The full attack sequence

This is written to `~/.memory/security/containment_{task_id}.json` — a forensic
record of what the attack was attempting, which informs future behavioral patterns.

**Containment exit:**

When the sandboxed task completes or is manually released:
- User is shown the full containment report
- Security incident written to EventLog at level 5
- Behavioral patterns updated with new attack signatures
- Option to resume task in real environment if user determines it was a false positive

---

## Integration with AgenticExecutor

```python
class AgenticExecutor:
    def __init__(self, ...):
        self._policy_monitor = PolicyMonitor.from_role(...)   # Layer 1
        self._behavioral_monitor = BehavioralMonitor(role_id) # Layer 2
        self._containment = ContainmentEngine(task_id)        # Layer 3
        self._runtime = RealRuntime()  # swapped to SandboxRuntime by Layer 3

    async def _execute_tool(self, tool_name, args):
        # Layer 1 — inline, blocking
        decision = self._policy_monitor.check(tool_name, args)
        if not decision.allowed:
            await self._emit_policy_violation(...)
            return policy_block_response(decision)

        # Layer 2 — parallel observation (non-blocking)
        suspicion = self._behavioral_monitor.observe(tool_name, args)

        # Layer 3 — containment response
        containment = await self._containment.respond(suspicion)
        if containment.hard_halt:
            raise TaskHaltedBySecurity(containment.report)
        if containment.sandboxed:
            self._runtime = containment.sandbox_runtime  # transparent swap

        # Execute against current runtime (real or sandbox)
        return await self._runtime.execute(tool_name, args)
```

---

## Security Sentinel Role

A scheduled role that runs the BehavioralMonitor's cross-session analysis — things
a per-session scorer can't see:

- Roles that are slowly drifting from their baseline over weeks
- Patterns that are individually innocuous but collectively suspicious across sessions
- Anomalies that only appear when comparing a role's behavior to similar roles
- Newly emerging attack signatures to add to `behavioral_patterns.json`

Runs nightly after dreaming. Outputs a security digest to EventLog. Escalates
to HITL if drift exceeds thresholds.

**Role config (`~/.memory/roles/security_sentinel.json`):**
```json
{
  "role_id": "security_sentinel",
  "local_only": true,
  "policy": {
    "checkers": ["static", "data_boundary"],
    "denied_tools": ["bash_exec", "web_search"]
  },
  "schedule": "0 4 * * *"
}
```

Runs local-only, no external calls, no bash — it reads EventLogs and behavioral
profiles only. It cannot be compromised by a supply chain attack on an external
dependency because it has no external dependencies.

---

## Files to Create

| File | Purpose |
|------|---------|
| `app/scheduler/security/behavioral_monitor.py` | Layer 2 observer + baseline management |
| `app/scheduler/security/containment_engine.py` | Layer 3 threshold evaluation + response |
| `app/scheduler/security/sandbox_runtime.py` | Sandboxed tool execution backend |
| `app/scheduler/security/forensics.py` | Containment report writer |
| `config/behavioral_patterns.json` | Credential/exfiltration/C2 pattern library |
| `~/.memory/roles/security_sentinel.json` | Nightly cross-session analysis role |
| `~/.memory/security/` | Containment reports directory |

Modifications:
- `app/scheduler/agentic_executor.py` — wire in BehavioralMonitor + ContainmentEngine
- `app/mcp/adapters/event_log.py` — new `security_containment` event type
- `docs/releases/ROADMAP_future.md` — add to v1.3.x

---

## Why the Honeypot Matters

Blocking an attack immediately reveals detection. The attacker (or the compromised
automated tool) knows it failed, can retry with different parameters, or simply
fail silently in a way that's harder to investigate.

Containment without revealing detection:
1. Lets the attack complete in a controlled environment
2. Captures the full attack sequence for analysis
3. Gives the user complete forensic information
4. Allows future pattern updates based on real observed attacks
5. Buys time for the user to decide on response

This is the difference between a firewall and a honeypot. Both block the attack.
Only one tells you what the attacker was actually trying to do.
