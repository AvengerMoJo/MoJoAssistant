# Bridle Bonsai — Multi-Agent Communication Patterns

## Overview

Bonsai is MoJoAssistant's self-regulating growth framework. **Bridle** is its inter-agent communication layer — the set of patterns that let agents coordinate, challenge each other, and share knowledge without routing everything through the owner.

Five patterns. Two exist. Three are missing.

---

## Pattern Map

| Pattern | Status | Tool | Description |
|---|---|---|---|
| **Delegation** | ✅ exists | `dispatch_subtask`, `scheduler_add_task` | Orchestrator assigns work to a specialist and waits or fires-and-forgets |
| **Cross-Verification** | ✅ exists (partial) | `dispatch_subtask` chain | Agent A produces → Agent B reviews → result returned to A |
| **Peer-to-Peer** | ❌ missing | — | Agent mid-task consults a peer without creating a full scheduled task |
| **Negotiation** | ❌ missing | — | Two agents with conflicting constraints converge on a shared decision |
| **Broadcast** | ❌ missing | — | Agent publishes a fact/capability change; all interested agents are notified |

---

## 1. Delegation ✅

**What it is:** An orchestrator role assigns a goal to a specialist and either waits for the result (`dispatch_subtask`) or schedules it asynchronously (`scheduler_add_task`).

**How it works today:**
```
Paul (orchestrator)
  └─ dispatch_subtask(role_id='researcher', goal='...')  → blocks, gets result
  └─ scheduler_add_task(role_id='popo', goal='...')      → async, fire-and-forget
```

**Constraints:**
- Max dispatch depth: 2 (sub-tasks cannot themselves dispatch sub-tasks)
- `dispatch_subtask` polls every 2s with a 5-minute default timeout
- Parent task ID is linked for dashboard tracing

**Good for:** Paul → Popo handoff, Paul → Rebecca research, orchestrator → multiple specialists in sequence.

---

## 2. Cross-Verification ✅ (partial)

**What it is:** Agent A produces output → Agent B independently reviews it → result returned to requester. Used for quality gates: research → review, code → review.

**How it works today:**
```
Orchestrator
  └─ dispatch_subtask(role_id='researcher', goal='research X')
      → result_A
  └─ dispatch_subtask(role_id='reviewer', goal=f'review this: {result_A}')
      → final_verified_result
```

**What's missing:** This is currently manual — the orchestrator has to explicitly chain the calls. There's no built-in "verify this output" primitive. Rebecca can't directly ask the reviewer to check her work; an orchestrator must mediate.

**Gap:** No direct agent-to-agent output handoff without an orchestrator in the middle.

---

## 3. Peer-to-Peer ❌ MISSING

**What it is:** An agent mid-task needs a quick expert opinion from another agent — not a full delegated task, but a synchronous consultation. The peer answers from their expertise and returns, with no task record created.

**Example:**
```
Rebecca (researching AI market trends) hits a technical claim she can't verify.
She needs Anna's engineering opinion — "is this architecture feasible?"
Anna responds in one pass. Rebecca incorporates the answer and continues.
```

**Why it doesn't exist today:** `dispatch_subtask` creates a full scheduler task with its own session, iterations, and report. It's too heavy for a quick "what do you think?" It also has a depth limit of 2, so a sub-task can't consult a peer.

**Design proposal — `consult_peer(role_id, question)`:**

```python
# New tool registered for roles with 'orchestration' capability
consult_peer(
    role_id="anna",
    question="Is a 1B parameter model capable of reliable tool calling?",
    context="optional — truncated relevant context from current task",
    max_tokens=500,  # short answer expected
)
# Returns: {"answer": "...", "role": "anna", "model": "..."}
```

**Implementation:** Single LLM call using the peer's system prompt + question. No scheduler task, no session file, no iteration loop. Just one inference call through the resource pool using the peer role's model_preference and persona. Response is returned inline to the calling agent.

**Depth consideration:** Peer consults do NOT count toward dispatch depth — they're stateless inference calls, not task dispatches.

---

## 4. Negotiation ❌ MISSING

**What it is:** Two agents with potentially conflicting constraints or goals need to converge on a shared decision. Neither agent's goal alone can fully satisfy all requirements — the solution requires both perspectives.

**Example:**
```
Rebecca: "We should acquire this $500 dataset for comprehensive market coverage."
Paul:    "Budget cap is $200. We need a free alternative or a scoped subset."
→ Negotiation: Rebecca proposes subset + free source combo. Paul approves.
```

**Why it doesn't exist today:** There's no mechanism for two agents to exchange proposals and counter-proposals. All decisions go through the owner (HITL) or through an orchestrator who imposes a resolution.

**Design proposal — `negotiate(role_id, proposal, constraints)`:**

Negotiation is a structured multi-turn exchange with a termination condition:

```
Phase 1 — Proposal
  Agent A: negotiate(role_id='paul', proposal='acquire $500 dataset', constraints=['full coverage needed'])

Phase 2 — Counter
  Paul evaluates against his constraints, responds with counter-proposal or accept/reject + reason

Phase 3 — Convergence (max N rounds)
  Agents exchange proposals until:
    (a) both accept → agreement returned
    (b) max rounds exceeded → escalate to ask_user with both positions
    (c) one agent calls break → escalate immediately
```

**Key design rules:**
- Max rounds: 3 (prevent infinite back-and-forth)
- If no convergence → surface to owner via `ask_user` with both positions clearly stated
- The negotiation transcript is stored in the initiating task's session for audit
- Negotiation is symmetric — either agent can propose or accept
- Agreement is explicit (`{"status": "agreed", "resolution": "..."}`) not inferred

**Implementation:** Implemented as a tool `negotiate_with(role_id, proposal, constraints, max_rounds=3)` that runs a mini-loop: send proposal to peer via consult_peer, parse response for accept/counter/reject, continue or escalate.

---

## 5. Broadcast ❌ MISSING

**What it is:** An agent publishes a fact, decision, or capability change that other agents may need to know about — without requiring a direct recipient. Interested agents receive it at their next session start or via a subscription.

**Example:**
```
Ahman registers a new network tool: `wireguard_peer_add`.
All roles with 'terminal' capability should know this tool now exists.
Rebecca's next task should have `wireguard_peer_add` available without manual reconfiguration.
```

**Why it doesn't exist today:** There's a `_broadcast` method in `scheduler/core.py` but it only sends events to SSE/push adapters (for the dashboard and ntfy). It does not write to any agent-readable store or update capability catalogs.

**Design proposal — `broadcast_to_agents(topic, payload)`:**

```python
broadcast_to_agents(
    topic="capability.new_tool",
    payload={
        "tool_name": "wireguard_peer_add",
        "capability_category": "terminal",
        "description": "Add a WireGuard peer node to the mesh",
        "contributed_by": "ahman",
    }
)
```

**Two delivery modes:**

**Mode A — Capability Broadcast (structural):** Writes to `capability_catalog.json`. All agents picking up tasks after this point will have the new tool available if their role has the matching capability category. No agent needs to be running.

**Mode B — Knowledge Broadcast (semantic):** Writes a KnowledgeUnit to the shared knowledge base (not role-scoped — global). Any agent calling `knowledge_search` with a relevant query will find it. The dreaming pipeline can consolidate it like any other document.

**What broadcast does NOT do:** It does not interrupt running tasks. Agents pick up broadcasts at session start or via `get_context`. This is eventual consistency, not real-time push to running agents. (Real-time interruption is a future capability.)

---

## Implementation Roadmap

### Phase 1 — Peer-to-Peer (lowest effort, highest value)
- New tool: `consult_peer(role_id, question, context?, max_tokens?)`
- Single LLM call, no scheduler involvement
- Register for roles with `orchestration` capability
- Estimated: 1–2 days

### Phase 2 — Broadcast (structural)
- New tool: `broadcast_to_agents(topic, payload)`
- Mode A: writes to capability catalog (immediate structural effect)
- Mode B: writes to global knowledge store (semantic, picked up via search)
- Estimated: 1 day

### Phase 3 — Negotiation (most complex)
- New tool: `negotiate_with(role_id, proposal, constraints, max_rounds?)`
- Built on top of `consult_peer` (uses same single-call inference)
- Termination: agreement | max_rounds → ask_user
- Estimated: 2–3 days

### Phase 4 — Cross-Verification primitive
- New tool: `verify_with(role_id, content, criteria?)`
- Shorthand for dispatch_subtask to a reviewer role with structured output
- Returns: `{verdict: pass|fail|partial, feedback: "...", confidence: 0.0–1.0}`
- Estimated: 1 day

---

## How They Fit Together

```
Owner
  │
  │ delegates goal
  ▼
Orchestrator (Paul)
  │
  ├─ [Delegation]     dispatch_subtask → Researcher (Rebecca)
  │                         │
  │                         ├─ [Peer-to-Peer]  consult_peer → Engineer (Anna)
  │                         │                      (quick technical check)
  │                         │
  │                         └─ [Broadcast]     broadcast_to_agents(topic='new_finding', ...)
  │
  ├─ [Cross-Verify]   dispatch_subtask → Reviewer (code review, fact check)
  │
  └─ [Negotiation]    negotiate_with → Budget Manager
         │
         └─ If no agreement → ask_user (with both positions)
```

---

## Demo Relevance

For the upcoming event demo, **Delegation** and **Cross-Verification** are demo-ready today. The story to tell for the missing three:

- **Peer-to-Peer**: "Rebecca can ask Anna a question mid-task — we're building this now"
- **Negotiation**: "When agents disagree, they negotiate — or escalate to you"
- **Broadcast**: "Ahman adds a tool; every agent knows about it automatically"

These three are the **community contribution opportunity** — each is a bounded, well-defined module that an open-source contributor can own end-to-end.

---

*Document version 1 — 2026-05-31*
