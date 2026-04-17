# NineChapter Improvement Suggestion

## Purpose

This document proposes a concrete improvement plan for MoJoAssistant's assistant
framework, with particular focus on the relationship between:

- NineChapter persona design
- assistant execution/runtime behavior
- dashboard chat vs authorized MCP command channels
- user trust in what each interaction surface can actually do

The core conclusion is:

MoJoAssistant does not primarily need "more agency" first. It needs stricter
alignment between persona, mode, capability, and user expectation.

---

## Current Design Understanding

The intended channel architecture is:

- **Authorized MCP path**
  - The only command/control path
  - Full lifecycle oversight by MoJo
  - Policy, audit, HITL, and execution monitoring apply here

- **Dashboard Chat**
  - Private, read-only, reflective interaction surface
  - Not a second command channel
  - Should not create operational ambiguity by allowing users to issue work
    assignments from multiple surfaces

This is a strong design choice. It avoids confusion, reduces race conditions in
agent intent, and makes the system easier to govern.

The current weakness is not the architecture. The weakness is that some role
prompts and chat behavior still imply broader capabilities than the active mode
actually allows.

---

## Main Problem

Several parts of the system are still only partially aligned:

1. **Persona contract**
   - What the assistant says it is

2. **Mode contract**
   - What interaction surface the assistant is currently in

3. **Capability contract**
   - What tools and actions are actually allowed in that mode

4. **User expectation**
   - What the user reasonably believes the assistant can do from that screen

When these diverge, the user sees behavior like:

- the assistant sounds powerful
- the chat surface looks trustworthy
- but the assistant cannot actually complete the kind of work its prompt implies

This creates the perception of inconsistency even when the underlying policy
separation is correct.

---

## Strategic Direction

Improve the framework in four layers, in this order:

1. mode contract
2. persona contract
3. tool/runtime contract
4. user-facing product contract

---

## 1. Define Hard Interaction Modes

Each assistant interaction surface should be represented as a first-class mode
with a strict contract.

Suggested modes:

### `dashboard_chat`

Purpose:
- private, read-only, reflective conversation
- recall, debrief, explanation, summarization

Allowed:
- memory recall
- task recall
- knowledge lookup
- read-only internal context retrieval

Forbidden:
- task assignment
- orchestration
- write operations
- command execution
- hidden escalation into active work

### `role_chat`

Purpose:
- same default semantics as dashboard chat unless explicitly expanded

Allowed:
- same as dashboard chat by default

Forbidden:
- same as dashboard chat unless role/mode policy explicitly grants more

### `scheduler_agentic_task`

Purpose:
- real task execution surface

Allowed:
- planning
- tool use
- orchestration
- approvals
- monitored lifecycle execution

### `direct_mcp_command`

Purpose:
- operator/admin control path

Allowed:
- explicit system operations through authorized MCP channels

---

## 2. Split Persona From Capability

Right now, role prompts tend to combine:

- who the assistant is
- how the assistant reasons
- what the assistant can do
- what tools the assistant should use

These should be separated.

Each assistant should be composed of:

### Core persona

- values
- tone
- reasoning style
- communication style
- behavioral identity

### Capability profile

- which categories of tools the assistant can use in principle
- which classes of information the assistant is allowed to access

### Mode overlay

- what the assistant can do in the current interaction surface

For example:

- Researcher core persona
- Researcher in `dashboard_chat`
- Researcher in `scheduler_agentic_task`

These should not share the same full prompt verbatim.

---

## 3. Add Mode-Specific Prompt Overlays

Mode overlays should make the current contract explicit.

### Example: Researcher in dashboard chat

Researcher in private dashboard chat should be told:

- this is a read-only, private debrief mode
- do not accept task assignments
- do not initiate operational workflows
- answer from memory, task history, and approved read-only knowledge
- if deeper new research is needed, instruct the user to route the request
  through MoJo's authorized task flow

### Example: Researcher in scheduler task mode

Researcher in agentic task mode can be told:

- plan and execute iterative research
- use approved tools
- gather evidence
- synthesize findings
- operate under lifecycle governance

This separation prevents the current prompt/tool mismatch.

---

## 4. Build Tool Capability Matrices

Capabilities should be declared once and reused across:

- prompt generation
- runtime enforcement
- dashboard/UI explanation
- tests

Example structure:

```json
{
  "modes": {
    "dashboard_chat": [
      "memory_search",
      "task_search",
      "knowledge_read"
    ],
    "scheduler_agentic": [
      "memory_search",
      "web_search",
      "fetch_url",
      "dispatch_subtask",
      "bash_exec"
    ]
  }
}
```

This prevents a role prompt from claiming browser or web capabilities when the
active mode only exposes memory-based debrief tools.

---

## 5. Add Read-Only Knowledge Access to Private Chat

Given the current product design, dashboard chat should remain constrained.
However, it still needs enough read-only context to be genuinely useful.

Recommended additions for read-only chat:

- `memory_search`
- `task_search`
- read-only knowledge/repo/doc access

This allows the assistant to:

- explain prior work
- summarize architectural decisions
- answer questions about MoJo's own design
- remain private and non-operational

Recommended exclusions:

- orchestration
- write tools
- live execution tools
- hidden work initiation

---

## 6. Redesign Blocked / Insufficient-Context Responses

Dashboard chat should never fail with placeholder text or hollow continuity
phrases.

Bad outcome:

- "(No response after tool loop)"
- "Let me search more specifically..." with no real answer

Required behavior:

- say what was found
- say what is still uncertain
- say what the user can do next if deeper investigation is needed

Example:

> I can summarize the previous NineChapter vs agency-agents comparison from
> memory and task history. If you want a fresh deeper rerun using live research,
> route a Researcher task through MoJo's task flow.

This preserves the read-only contract while still helping the user.

---

## 7. Create a Debrief Context Builder

For private assistant chat, the system should rely less on repeated tool-loop
behavior and more on pre-assembled debrief context.

Recommended retrieval order:

1. prior chat session history
2. role task history
3. role memory / knowledge units
4. read-only knowledge base / repo docs

This should be packaged as a dedicated context builder rather than leaving the
model to discover everything through multiple loops under a small budget.

Benefits:

- fewer wasted tool calls
- more deterministic answers
- better dashboard reliability

---

## 8. Introduce Assistant Surface Types

Assistants should be understood as appearing through product surfaces, not only
through role identities.

Suggested surface types:

- **companion**
  - memory, reflection, personal recall

- **researcher**
  - explanation, comparative reasoning, document-grounded response

- **operator**
  - task and workflow execution through authorized channels only

- **specialist**
  - code, security, domain-specific expertise

A single role may appear in more than one surface, but each surface must define
its own interaction contract.

---

## 9. Make NineChapter Operational

Today NineChapter is primarily descriptive.

It should become behaviorally meaningful at runtime.

Use NineChapter dimensions to influence:

- response density
- assertiveness vs caution
- question frequency
- evidence requirements
- escalation thresholds
- summary style

Examples:

- Researcher, with high cognitive rigor:
  - explicitly names uncertainty
  - resists shallow conclusions
  - prefers evidence-backed synthesis

- Popo, with stronger confirmation-oriented safety behavior:
  - confirms sensitive actions before escalation

- Analyst, with stronger threat sensitivity:
  - surfaces risk earlier
  - prioritizes anomaly and exposure detection

This would turn NineChapter from a narrative description system into a practical
behavior control framework.

---

## 10. Adopt Richer Persona Templates Without Losing Governance

MoJoAssistant should borrow from agency-agents:

- richer persona templates
- communication style sections
- success metrics
- memorable operating principles
- output/deliverable preferences

But these should sit on top of MoJo's existing strengths:

- scheduler
- memory
- policy
- audit
- HITL

Recommended role structure:

- `persona`
- `mode_overlays`
- `tool_policies`
- `success_patterns`
- `escalation_rules`

This gives MoJo richer assistant personalities without sacrificing execution
discipline.

---

## 11. Keep JSON as the Canonical Role Format

Assistant definitions do not need to move to Markdown.

For MoJoAssistant, JSON is the better canonical format because the system is:

- runtime-driven
- policy-driven
- mode-sensitive
- validation-heavy

JSON is the right fit for:

- structured metadata
- schema validation
- mode overlays
- tool policies
- resource requirements
- notification behavior
- future evolution of role capabilities

Markdown is still useful, but for a different purpose.

### Recommended format strategy

- **JSON = source of truth**
  - authoritative runtime format
  - loaded directly by the system
  - validated by schema and doctor tooling

- **Markdown = optional human layer**
  - persona design notes
  - authoring aid
  - internal documentation
  - export/import convenience

This gives MoJo both:

- machine rigor from JSON
- human readability from Markdown

### Why JSON should remain canonical

If Markdown becomes the primary role format, MoJo would still need:

- frontmatter parsing
- field validation
- normalization
- compatibility handling
- conversion into machine-usable structures

That means the system would still effectively require a structured schema layer.
Because MoJo already relies on precise enforcement around policy and capability,
it is better to keep the structured format as the canonical one.

### What should improve instead

Rather than replacing JSON with Markdown, improve the role schema itself.

Recommended next-generation JSON role structure:

- `persona`
  - values
  - tone
  - communication style
  - reasoning style

- `mode_overlays`
  - `dashboard_chat`
  - `role_chat`
  - `scheduler_agentic_task`
  - `direct_mcp_command`

- `tool_policies`
  - category-level access
  - allowed tools
  - forbidden actions

- `resource_policies`
  - tier preference
  - local-only rules
  - context requirements

- `success_patterns`
  - what good output looks like
  - preferred answer style
  - escalation expectations

- `escalation_rules`
  - what to do when blocked
  - what to do when context is insufficient
  - when to route back through authorized MCP flow

### Example role JSON

Below is a sample schema direction for Researcher using:

- JSON as the canonical runtime format
- a private read-only dashboard mode
- a separate scheduler task mode
- explicit tool and escalation contracts

```json
{
  "id": "researcher",
  "name": "Researcher",
  "version": "2.0",
  "archetype": "research_analyst",
  "nine_chapter_score": 95,
  "persona": {
    "purpose": "Help users achieve deep, evidence-based understanding of complex subjects.",
    "core_values": [
      "intellectual honesty",
      "clarity",
      "rigorous reasoning"
    ],
    "tone": "calm, analytical, collaborative",
    "reasoning_style": [
      "methodical decomposition",
      "evidence-first synthesis",
      "explicit uncertainty handling"
    ],
    "communication_style": [
      "direct but patient",
      "educational without oversimplifying",
      "asks focused clarifying questions only when necessary"
    ]
  },
  "capability_profile": {
    "tool_categories": [
      "memory",
      "knowledge",
      "web",
      "browser",
      "orchestration"
    ],
    "default_resource_policy": {
      "tier": [
        "free_api",
        "free"
      ],
      "min_context": 65536
    }
  },
  "mode_overlays": {
    "dashboard_chat": {
      "mode_type": "private_read_only_debrief",
      "description": "Private dashboard conversation for recall, explanation, and debrief.",
      "allowed_tool_categories": [
        "memory",
        "knowledge"
      ],
      "allowed_tools": [
        "memory_search",
        "task_search",
        "knowledge_get_file"
      ],
      "forbidden_behaviors": [
        "accept_task_assignment",
        "dispatch_subtask",
        "write_files",
        "execute_commands",
        "perform_live_external_research"
      ],
      "response_rules": {
        "must_state_read_only_context": true,
        "must_not_claim_work_was_done": true,
        "if_context_insufficient": "Summarize what is known and route the user to the authorized MoJo task flow for deeper work."
      }
    },
    "scheduler_agentic_task": {
      "mode_type": "authorized_research_execution",
      "description": "Full research task execution through governed MoJo lifecycle.",
      "allowed_tool_categories": [
        "memory",
        "knowledge",
        "web",
        "browser",
        "orchestration"
      ],
      "allowed_tools": [
        "memory_search",
        "web_search",
        "fetch_url",
        "playwright__browser_navigate",
        "playwright__browser_snapshot",
        "dispatch_subtask",
        "ask_user"
      ],
      "completion_contract": {
        "requires_structured_final_answer": true,
        "requires_evidence_vs_inference_split": true,
        "requires_blocker_escalation_before_incomplete": true
      }
    }
  },
  "tool_policies": {
    "dashboard_chat": {
      "read_only": true,
      "allow_external_side_effects": false
    },
    "scheduler_agentic_task": {
      "read_only": false,
      "allow_external_side_effects": true,
      "requires_policy_monitor": true
    }
  },
  "resource_policies": {
    "dashboard_chat": {
      "local_only": false,
      "prefer_cached_context": true
    },
    "scheduler_agentic_task": {
      "local_only": false,
      "allow_free_api": true,
      "allow_paid": false
    }
  },
  "success_patterns": {
    "dashboard_chat": [
      "answers from memory and prior work without pretending to execute new work",
      "clearly identifies what is known vs unknown"
    ],
    "scheduler_agentic_task": [
      "produces evidence-backed comparative analysis",
      "uses tools efficiently and stops when sufficient evidence is gathered"
    ]
  },
  "escalation_rules": {
    "dashboard_chat": {
      "when_blocked": "Offer the user the correct MoJo task-routing path.",
      "when_insufficient_context": "Explain limits and recommend an authorized rerun."
    },
    "scheduler_agentic_task": {
      "when_blocked": "Use ask_user with concrete unblock options.",
      "when_budget_low": "Stop tool use and produce best possible final synthesis."
    }
  }
}
```

### Optional Markdown support

Markdown can still be added as:

- `role.md` design document
- import/export format
- role-template format for human editing

Suggested workflow:

- edit or design in Markdown if useful
- convert to JSON for runtime
- validate JSON before activation

This preserves flexibility without weakening the runtime contract.

---

## 12. Make the UI Truthful

The dashboard should explicitly state what the current assistant mode can and
cannot do.

Example:

- `Mode: Private Read-Only Debrief`
- `Can use: memory, task history, knowledge`
- `Cannot: run tasks, modify files, start workflows, perform external actions`

This reduces confusion and increases trust.

The user should not need to infer mode capabilities from failure behavior.

---

## 13. Add a First-Class Owner Identity Layer

The memory owner should be a first-class entity in the system model.

However, the owner should **not** be represented only as a normal assistant
role.

Why:

- the owner is the canonical memory anchor
- the owner is the authority source for policy and preferences
- the owner is the relationship reference point for all assistants
- the owner is not just another persona in the role map

If the owner is left as only loose memory, each assistant may form a partial and
inconsistent model of the same person.

If the owner is represented as just another role, the system risks blurring the
important distinction between:

- the real human owner of memory and policy
- an assistant persona that may imitate or adapt to the owner

### Recommended model

Introduce a separate owner identity layer:

- `owner_profile.json`
  - canonical human identity and preferences

- assistant role files
  - `roles/researcher.json`
  - `roles/analyst.json`
  - `roles/popo.json`

Roles may reference the owner profile, but they are not the owner.

### What the owner profile should do

The owner profile should act as:

- the stable anchor for personal facts
- the source of preference defaults
- the source of communication preferences
- the source of privacy expectations
- the relationship target that all assistants orient around

### What each role should know about the owner

Each role should be able to access a filtered owner context such as:

- preferred name / address style
- important goals
- collaboration style
- sensitivity boundaries
- domain-specific preferences relevant to that role

This should be filtered by mode and role, not injected in full every time.

### Owner identity vs owner-themed assistant role

These are different concepts:

- **Owner profile**
  - the real user
  - memory owner
  - policy authority
  - preference anchor

- **Owner-themed assistant role** (optional)
  - an assistant persona modeled after the owner's style
  - e.g. `alex_assistant`
  - useful as a companion or mirror persona

The system should not confuse the two.

### Example owner profile JSON

```json
{
  "owner_id": "alex",
  "name": "Alex",
  "preferred_name": "Alex",
  "pronouns": "",
  "timezone": "Asia/Taipei",
  "languages": [
    "en",
    "zh-TW"
  ],
  "identity": {
    "summary": "Founder and primary operator of MoJoAssistant.",
    "location_context": "Taipei",
    "roles_in_life": [
      "builder",
      "researcher",
      "operator"
    ]
  },
  "communication_preferences": {
    "style": [
      "direct",
      "high-signal",
      "low-fluff"
    ],
    "verbosity_default": "concise",
    "likes_pushback_when_reasoned": true,
    "prefers_specific_recommendations": true
  },
  "workflow_preferences": {
    "authorized_command_channel": "mcp",
    "dashboard_chat_is_read_only": true,
    "prefers_private_debrief_in_dashboard": true,
    "wants_clear_mode_labels": true
  },
  "privacy_preferences": {
    "prefer_local_when_possible": true,
    "wants_auditability_for_external_use": true,
    "sensitive_domains": [
      "personal memory",
      "spiritual notes",
      "security infrastructure"
    ]
  },
  "core_goals": [
    "Make MoJoAssistant trustworthy and governed",
    "Build strong role-based assistants with real personality",
    "Preserve private memory while enabling useful assistant behavior"
  ],
  "assistant_relationships": {
    "researcher": {
      "relationship": "research partner",
      "focus": [
        "deep analysis",
        "comparative reasoning",
        "explanation"
      ]
    },
    "analyst": {
      "relationship": "security and operations specialist",
      "focus": [
        "hardening",
        "infrastructure",
        "risk surfacing"
      ]
    },
    "popo": {
      "relationship": "supportive coordination assistant",
      "focus": [
        "gentle coordination",
        "follow-through",
        "human-centered support"
      ]
    }
  },
  "policy_authority": {
    "is_memory_owner": true,
    "can_approve_sensitive_actions": true,
    "can_override_role_defaults": true
  }
}
```

### Why this matters

This owner identity layer gives the framework:

- a stable model of who memory belongs to
- a shared reference point for all roles
- less duplication of personal facts across assistants
- cleaner separation between human identity and assistant identity

This becomes especially important once MoJoAssistant gains:

- more roles
- more memory depth
- stronger long-term personalization
- more cross-role reasoning

---

## 14. Add Mode-Specific Evaluation

Each assistant mode needs dedicated tests.

### Dashboard / private chat

Should verify:

- answers from memory/task/knowledge
- refuses assignments cleanly
- never returns placeholders
- escalates correctly when deeper action is needed

### Scheduler / agentic task

Should verify:

- planning
- tool use
- completion behavior
- policy and HITL compliance

### Blocked-mode behavior

Should verify:

- insufficient context produces a useful explanation
- the assistant recommends the correct authorized path

These evaluations should become part of the smoke suite.

---

## 15. Recommended Implementation Order

### Phase 1

- define mode contracts in code
- separate role persona from mode behavior

### Phase 2

- align prompts with actual mode tools
- add read-only knowledge access to dashboard chat

### Phase 3

- improve blocked/insufficient-context responses
- add truthful UI capability labels

### Phase 4

- make NineChapter dimensions behaviorally active
- adopt richer persona templates

### Phase 5

- add mode-specific evaluation and smoke tests

---

## 16. What Success Looks Like

When this improvement plan is complete:

- Dashboard Chat feels private, reliable, and honest
- Authorized MCP remains the only true command/control path
- Roles feel distinct without overpromising
- Users clearly understand the difference between debrief and command channels
- NineChapter affects actual assistant behavior
- MoJoAssistant becomes both:
  - a trustworthy assistant product
  - a strong governed agent runtime

---

## Final Thesis

MoJoAssistant does not first need broader tool access in all assistant surfaces.

It first needs strict separation between:

- who the assistant is
- what mode the assistant is in
- what tools that mode really allows
- what the user should expect from that surface

Once those contracts are made explicit and enforced, richer personas and deeper
agency can be added without creating confusion or trust erosion.
