# Bridle Bonsai — Communication Patterns: Design Spec
## Wire, Trigger, and the Bonsai Loop

*Architecture document for multi-agent coordination in MoJoAssistant.*
*Supersedes the plugin-oriented v1 spec.*

---

## 0. The Central Insight

Delegation and Cross-Verification feel natural because they are **usage patterns of one existing primitive** — `dispatch_subtask`. No new tool. The orchestrator just composes the same call differently.

```
Delegation:       goal → dispatch_subtask(researcher) → result
Cross-Verification: goal → dispatch_subtask(researcher) → dispatch_subtask(reviewer) → result
```

The three missing patterns — Peer-to-Peer, Negotiation, Broadcast — must follow the same rule: **extend existing primitives, don't add plugins**. The goal is fewer concepts, not more tools.

But there is a second, harder problem. Delegation and Cross-Verification work because **the trigger is always explicit** — it is written into the goal by the owner or orchestrator. Rebecca doesn't decide to dispatch; she's told to in her goal. The three missing patterns require agents to self-trigger — and that's where the real design lives.

This spec covers both layers:
- **The wire**: how communication physically happens (what primitives carry the message)
- **The trigger**: what causes an agent to initiate communication in the first place

---

## 1. The Two-Layer Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    TRIGGER LAYER                          │
│  (WHY does an agent communicate? WHO does it call?)       │
│                                                           │
│  Today:     Owner/orchestrator writes it into the goal   │
│  Near-term: Role's collaboration map field               │
│  Long-term: Bonsai learns from iteration failures        │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│                     WIRE LAYER                            │
│  (HOW does the message physically travel?)                │
│                                                           │
│  Existing:  dispatch_subtask, add_conversation            │
│  Extension: dispatch_subtask(consult=True)               │
│  New:       broadcast_to_agents(mode='capability')        │
└──────────────────────────────────────────────────────────┘
```

The wire layer is what this document specifies. The trigger layer is what Bonsai develops over time.

---

## 2. Pattern Map — Updated

| Pattern | Wire | Trigger today | Trigger future |
|---|---|---|---|
| **Delegation** ✅ | `dispatch_subtask` | Explicit in goal | — |
| **Cross-Verification** ✅ | `dispatch_subtask` chain | Explicit in goal | — |
| **Peer-to-Peer** | `dispatch_subtask(consult=True)` | Orchestrator front-loads the peer name in the goal | Bonsai adds peer to role's collaboration map after missed consultations |
| **Negotiation** | Orchestrator loop over `dispatch_subtask(consult=True)` | Orchestrator front-loads the constraint holder in the goal | Bonsai recognizes recurring constraint conflicts |
| **Broadcast (knowledge)** | `add_conversation(scope='framework')` + `knowledge_search` | Agent decides post-completion | Workflow template teaches: "share significant findings" |
| **Broadcast (capability)** | `broadcast_to_agents(mode='capability')` | Agent decides post-capability creation | Workflow template teaches: "broadcast new tools" |

---

## 3. Wire Specification: Peer-to-Peer

### What already exists

`dispatch_subtask` already creates a task, runs one agent, returns the result. A "consult" is just a dispatch with:
- `max_iterations=1` — peer answers once
- No session file written
- Depth limit bypass — peers can consult peers

The blocker: `dispatch_subtask` enforces `MAX_DISPATCH_DEPTH = 2`, which prevents sub-tasks from dispatching further. A consultation is not a dispatch — it's a question — and should bypass this limit.

### Proposed extension: `dispatch_subtask(consult=True)`

One new boolean parameter on the existing tool:

```python
dispatch_subtask(
    role_id="anna",
    goal="Is a 1B parameter model capable of reliable tool calling?",
    consult=True           # NEW — changes the execution mode
)
```

When `consult=True`:
- `max_iterations` forced to 1
- Depth limit bypassed (consult does not count toward dispatch depth)
- No session file written to `~/.memory/task_sessions/`
- Task record is ephemeral (not persisted to `~/.memory/task_reports/`)
- Response is the peer's first-turn reply

Everything else — resource acquisition, system prompt build, tool resolution — stays identical to a normal dispatch. Same code path, different mode.

### Files changed

| File | Change |
|---|---|
| `app/scheduler/capability_registry.py` | In `CapabilityDefinition("dispatch_subtask")`, add `consult` boolean to parameters schema |
| `app/scheduler/capability_registry.py` | In `_dispatch_subtask()`, check `args.get("consult")` — if True: skip depth check, force `max_iterations=1`, pass `ephemeral=True` to task |
| `app/scheduler/models.py` | Add `ephemeral: bool = False` to `Task` dataclass |
| `app/scheduler/core.py` | In `add_task()`, if `task.ephemeral`: skip persistence to task_reports |
| `app/scheduler/agentic_executor.py` | Check `task.ephemeral` before writing session file |

### Trigger today (zero new infrastructure)

The orchestrator writes it into the goal:

```
Goal for Rebecca: "Research AI chip market trends. If you encounter a hardware 
feasibility claim you cannot verify, consult Anna (role_id='anna', consult=True) 
before including it in your report."
```

Rebecca now knows: the condition (feasibility claim), the peer (Anna), and the mechanism (`consult=True`). The wire carries the message. The trigger is in the text.

### Trigger future (Bonsai)

After a task where Rebecca included an unverified claim that Anna later flagged in a review, Bonsai records:

```
Signal: Rebecca produced output that failed cross-verification on technical feasibility
Action: Add "anna" to Rebecca's collaboration map for "technical_feasibility"
Effect: Rebecca's next session includes "for technical feasibility questions, consult anna"
        in her workflow template — without the orchestrator having to say it
```

---

## 4. Wire Specification: Negotiation

### What already exists

Negotiation is not a new primitive. It is an **orchestration recipe** built from `dispatch_subtask(consult=True)` calls in a loop. The orchestrator runs the loop explicitly in its task.

The pattern:
```
current_proposal = initial_proposal
for round in range(max_rounds):
    response = dispatch_subtask(role_id=peer, goal=negotiation_prompt(current_proposal, constraints), consult=True)
    if "ACCEPT" in response:
        → done
    elif "COUNTER:" in response:
        current_proposal = extract_counter(response)
    elif "REJECT" in response:
        → break
else:
    ask_user(both positions)
```

This is orchestrator logic — the orchestrator writes this loop as part of its agentic iteration. No new tool needed.

### What makes it work

The orchestrator's goal must include:
1. The structured negotiation protocol (ACCEPT / COUNTER: / REJECT format)
2. The peer's role_id and what constraints they enforce
3. The max_rounds limit and escalation rule (ask_user if no convergence)

The workflow template for orchestration roles should include this recipe so orchestrators know how to negotiate without being told per-goal.

### Workflow template addition (the only deliverable for Negotiation)

Add to `config/workflow_templates/orchestrator.md`:

```markdown
## Negotiation Pattern

When you need a decision that requires satisfying another agent's constraints:

1. State your proposal clearly
2. Call dispatch_subtask(role_id=<constraint_holder>, goal=<see template below>, consult=True)
3. Parse response for ACCEPT / COUNTER: <new terms> / REJECT
4. If COUNTER: update proposal and repeat (max 3 rounds)
5. If no agreement after 3 rounds: call ask_user with both positions clearly stated

Negotiation goal template:
"[NEGOTIATION ROUND {n}/3]
My proposal: {proposal}
Your constraints (as I understand them): {their_constraints}
Respond with exactly: ACCEPT: <reason> | COUNTER: <your counter-proposal> | REJECT: <reason>"
```

### Trigger today

Orchestrator's goal explicitly names the negotiation:

```
Goal for Paul: "Rebecca wants to acquire a $500 dataset. Our budget cap is $200. 
Negotiate with Rebecca (role_id='rebecca') using the negotiation pattern — 
3 rounds max, then ask_user if no agreement."
```

### Trigger future (Bonsai)

After recurring budget overruns, Bonsai adds to Paul's role: "when a researcher proposes resource acquisition above $200, negotiate before approving." Paul self-triggers without being told.

---

## 5. Wire Specification: Broadcast

### Mode B — Knowledge broadcast (already works)

`add_conversation(scope='framework')` already writes to the shared framework knowledge store. Any agent calling `knowledge_search` finds it. This IS broadcast mode B. It works today.

What's missing: agents don't know to use it this way. The fix is documentation in the workflow template, not new code.

Add to the relevant workflow templates:

```markdown
## Sharing Findings

When you discover something every agent should know (a tool bug, a model behavior, 
a useful resource that survives beyond this task), call:

add_conversation(
    scope="framework",
    user_message="Finding: <topic>",
    assistant_message="<the finding in reusable form>"
)

Other agents will retrieve this via knowledge_search on relevant queries.
```

### Mode A — Capability broadcast (one new tool)

Writing a new tool entry to `capability_catalog.json` is structural — it changes what every future agent session can do. This cannot be done via `add_conversation`. It needs one targeted new tool.

**New tool: `broadcast_capability(tool_name, capability_category, description)`**

```python
broadcast_capability(
    tool_name="wireguard_peer_add",
    capability_category="terminal",
    description="Add a WireGuard peer node to the mesh",
) -> {
    "success": bool,
    "broadcast_id": str,
}
```

This is the only genuinely new tool in the entire Bridle implementation. It writes atomically to `capability_catalog.json`. No LLM call. No scheduler task. Pure data write.

**Capability gate**: `danger_level="medium"`, gated under `orchestration` category. Only agents that can orchestrate can structurally change the capability catalog.

### Files changed (Mode A only)

| File | Change |
|---|---|
| `app/scheduler/capability_registry.py` | Add `CapabilityDefinition("broadcast_capability")` |
| `app/scheduler/capability_registry.py` | Add `elif name == "broadcast_capability"` dispatch |
| `app/scheduler/capability_registry.py` | Add `async def _broadcast_capability(args)` — loads catalog, appends entry, atomic write |
| `app/scheduler/capability_resolver.py` | Add `"broadcast_capability"` to orchestration tools list |

---

## 6. The Trigger Layer — Collaboration Map (near-term data model)

For autonomous triggering without per-goal orchestrator instructions, roles need a social graph. Add an optional `collaboration` field to the role JSON schema:

```json
{
  "id": "rebecca",
  "collaboration": {
    "technical_feasibility":  { "role_id": "anna",  "how": "consult" },
    "budget_approval":        { "role_id": "paul",  "how": "negotiate" },
    "system_provisioning":    { "role_id": "ahman", "how": "dispatch" }
  }
}
```

At session start, the executor injects this map into Rebecca's system prompt:

```
## Collaboration Map
- Technical feasibility questions → consult Anna (role_id='anna')
- Budget decisions above your scope → negotiate with Paul (role_id='paul')
- System provisioning needs → dispatch to Ahman (role_id='ahman')
```

Now Rebecca can self-trigger without the orchestrator writing it into every goal. The map is maintained by the role owner — or eventually by Bonsai when it detects recurring patterns.

### Files changed (collaboration map)

| File | Change |
|---|---|
| `app/scheduler/agentic_executor.py` | In `_execute()`, after loading role: check `role.get("collaboration")` and build collaboration block |
| `app/scheduler/role_template_engine.py` | Add `_build_collaboration_block(role)` — returns formatted map or empty string |

---

## 7. The Bonsai Loop — Trigger Intelligence over Time

The full arc:

```
Task runs
  │
  ├─ Agent hits a situation where communication would have helped
  │   (technical claim unverified, budget conflict discovered late, missed finding)
  │
  ├─ Task completes (or fails, or gets cross-verified and fails)
  │
  ▼
Bonsai growth engine analyzes iteration history:
  - Did the agent ask for something it could have gotten from a peer?
  - Did a cross-verification step flag an error that a consult would have caught?
  - Did a resource acquisition fail budget review post-hoc?
  │
  ├─ If yes: generate a collaboration map entry
  │    {"technical_feasibility": {"role_id": "anna", "how": "consult"}}
  │
  └─ Write to role's JSON or workflow template refinement
       Next session: self-triggers without orchestrator direction
```

This is what closes the loop. The wire enables communication. Bonsai teaches the agent WHEN to use it.

---

## 8. Full Deliverable Summary

### What already works today (no code needed)
- Peer-to-Peer via `dispatch_subtask(max_iterations=1)` — depth limit is the only blocker
- Broadcast mode B via `add_conversation(scope='framework')` + `knowledge_search`
- Negotiation as an orchestrator-written loop using existing dispatch

### Minimal code changes (Phase 1 — pre-demo)
- Document broadcast mode B in workflow templates
- Document negotiation recipe in orchestrator workflow template

### Small targeted additions (Phase 2 — post-demo)
1. `dispatch_subtask(consult=True)` — bypass depth limit, ephemeral execution, forced single iteration
2. `broadcast_capability(tool_name, capability_category, description)` — the only genuinely new tool
3. `collaboration` field in role JSON + injection into session system prompt

### Trigger intelligence (Phase 3 — Bonsai wired)
4. Bonsai growth engine generates collaboration map entries from iteration failure signals
5. Workflow template refinement suggestions based on task outcome patterns

---

## 9. What Is Explicitly Out of Scope

- Real-time broadcast (interrupting running agents mid-task)
- Peer tool access during a consult (the peer cannot call tools in a consult response)
- Cross-agent session state sharing (agents share via knowledge store, not live memory)
- `verify_with` shorthand (Phase 4, separate spec)

---

## 10. Open Questions

1. **`consult=True` depth bypass**: should consults be fully uncapped (any depth), or capped at a separate `MAX_CONSULT_DEPTH`? Fully uncapped risks infinite consult chains; a cap of 1 (consultees cannot themselves consult) is the safest default.

2. **Collaboration map ownership**: who writes it — the role owner, the orchestrator, or Bonsai? For now: role owner writes, Bonsai suggests (requires confirmation before writing).

3. **Negotiation transcript persistence**: should the orchestrator be responsible for calling `add_conversation` after a negotiation, or should `dispatch_subtask(consult=True)` return a structured transcript that the orchestrator can optionally save?

---

*Document version 2 — 2026-06-01*
*Replaces version 1 (plugin-oriented spec, 2026-05-31)*
