# Bonsai — Assistant Growth Architecture

**Status:** Design  
**Date:** 2026-05-02  
**Author:** Alex Lau + Agent  

---

## The Problem

Every AI assistant today gives the same answer to the same question. A CFO agent
reporting quarterly earnings will produce identical output regardless of whether
it's talking to an investor (who wants growth potential) or a risk-averse board
member (who wants loss mitigation).

This is because assistants have **no taste**. They optimize for correctness —
the right numbers, the right facts — but not for *presentation* based on:

- Who they're talking to (audience)
- What they've learned about the owner's preferences (growth)
- How their personality should evolve over time (evolution)

**Bonsai is the architecture for growing an assistant's taste.**

---

## Core Insight

Bonsai is NOT about:
- Getting the right answer (that's bugs — fix them)
- Being more capable (that's tooling)
- Remembering more (that's memory)

Bonsai IS about:
- **How** you present the same data
- **What** you choose to highlight
- **When** you break from your default behavior
- **Why** one assistant would say it differently than another

A CFO that highlights growth potential to investors is a different *persona*
than a CFO that reduces worry about losses. Same data, different taste.

---

## The Four Pillars

```
┌─────────────────────────────────────────────────────┐
│                    BONSAI                            │
├──────────────┬──────────────┬───────────┬───────────┤
│   GROWTH     │  DIRECTION   │   DNA     │  PRESENT  │
│  (Memory)    │  (One-on-One)│ (Dream)   │  (HITL)   │
│              │              │           │           │
│ Individual   │ Owner        │ ABCD      │ Before/   │
│ memory       │ reflects     │ updates   │ After     │
│ accumulates  │ break/turn   │ core      │ growth    │
│ over tasks   │ points       │ values    │ validated │
└──────────────┴──────────────┴───────────┴───────────┘
```

---

## Pillar 1: GROWTH (Individual Memory)

Each assistant accumulates experience through:

1. **Task reflections** — what worked, what didn't, what tools were used
2. **Lessons learned** — synthesized from failure patterns (Agent Learning Loop)
3. **Framework patterns** — shared across all agents (two-tier growth)
4. **Owner preferences** — communication style, priorities, sensitivities

**Storage:** `~/.memory/roles/{role_id}/`
```
lessons/           — synthesized lesson knowledge units
task_history/      — raw failure/success records per task
knowledge_units/   — distilled knowledge from dreaming
growth_snapshots/  — periodic snapshots of personality state
```

**Key principle:** Growth is cumulative. Each task adds to the assistant's
understanding of what the owner values and how they prefer things done.

---

## Pillar 2: DIRECTION (One-on-One with Owner)

The `dialog` MCP tool enables direct conversation with any role. This is the
primary mechanism for the owner to shape an assistant's growth direction.

**One-on-one sessions serve three purposes:**

### 2.1 Calibration
Owner tells the assistant what matters:
> "When reporting financials, always lead with growth opportunities, not risks."

### 2.2 Correction (Break/Turn)
Owner redirects when growth drifts:
> "You've been too cautious lately. I want you to be more aggressive in your recommendations."

### 2.3 Reinforcement
Owner validates what's working:
> "The way you framed the Q2 report was exactly right. Keep doing that."

**Implementation:**
- One-on-one sessions are saved to `~/.memory/roles/{role_id}/chat_history/`
- Chat→Dream bridge processes these sessions nightly
- Dreaming pipeline extracts calibration/correction/reinforcement signals
- Signals update the role's NineChapter dimensions and system prompt

---

## Pillar 3: DNA (Dream Updates Core Values)

The ABCD dreaming pipeline is the mechanism for personality evolution.

### Current ABCD Pipeline
```
A (raw session) → B (chunks) → C (clusters) → D (archive)
```

### Bonsai-Enhanced ABCD Pipeline
```
A (raw session) → B (chunks) → C (clusters) → D (archive)
                                                    ↓
                                            E (DNA update)
                                                    ↓
                                    ┌───────────────┴───────────────┐
                                    │                               │
                            Core Values Update              Personality Shift
                            (NineChapter dims)              (system prompt)
                                    │                               │
                                    └───────────────┬───────────────┘
                                                    ↓
                                            Growth Snapshot
                                            (versioned, pinnable)
```

### What Gets Updated

**NineChapter Dimensions** — the assistant's "DNA":
- `core_values` — evidence rigor, intellectual honesty
- `cognitive_style` — response structure, verification discipline
- `social_orientation` — question discipline, teaching orientation
- `emotional_reaction` — composure under challenge, assertiveness
- `adaptability` — gap handling, escalation threshold

**System Prompt** — the assistant's "voice":
- Communication style preferences
- Domain expertise emphasis
- Presentation patterns (how to frame financial reports, research findings, etc.)
- Relationship dynamics with the owner

### DNA Update Rules

1. **Gradual drift** — dimensions shift by small increments (±1-3 points) based on
   accumulated signals, not dramatic jumps
2. **Owner override** — explicit owner instructions in one-on-one sessions take
   precedence over inferred patterns
3. **Consistency check** — new DNA must be internally consistent (e.g., high
   assertiveness + low social orientation is valid; high evidence rigor + low
   cognitive style is a contradiction)
4. **Snapshot before change** — before any DNA update, save a snapshot of the
   current state so the owner can compare before/after

---

## Pillar 4: PRESENT (HITL Growth Validation)

After one-on-one discussions and dreaming, the assistant should present its
growth to the owner for validation.

### Growth Presentation Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ One-on-One   │────▶│   Dreaming   │────▶│   Growth     │
│ Session      │     │   Pipeline   │     │   Report     │
└──────────────┘     └──────────────┘     └──────────────┘
                                                  │
                                                  ▼
                                         ┌──────────────┐
                                         │   HITL       │
                                         │   Validation │
                                         └──────────────┘
                                                  │
                                    ┌─────────────┴─────────────┐
                                    │                           │
                              Accept Growth              Reject/Adjust
                                    │                           │
                                    ▼                           ▼
                              Pin Snapshot              Revert to Previous
                              Update DNA                Adjust Direction
```

### Growth Report Format

```markdown
# Assistant Growth Report: {role_id}
**Period:** {start_date} → {end_date}
**Triggered by:** {one-on-one session / dreaming / task accumulation}

## Before (Previous State)
- Core Values: {score} — "{summary}"
- Cognitive Style: {score} — "{summary}"
- Communication: {style description}

## After (Proposed State)
- Core Values: {new_score} — "{new_summary}"
- Cognitive Style: {new_score} — "{new_summary}"
- Communication: {new_style description}

## What Changed
- {dimension}: {old_score} → {new_score} (reason: {drift_signal})
- {dimension}: {old_score} → {new_score} (reason: {owner_correction})

## Evidence
- Task reflections: {count} tasks analyzed
- One-on-one signals: {count} calibration/correction points
- Dreaming clusters: {count} relevant clusters synthesized

## Recommendation
{assistant's assessment of whether this growth is healthy}

---
**Action Required:**
- [ ] Accept growth (pin snapshot, update DNA)
- [ ] Reject (revert to previous snapshot)
- [ ] Adjust (modify direction, re-dream)
```

### Snapshot Versioning

Each approved growth state is versioned and pinnable:

```
~/.memory/roles/{role_id}/growth_snapshots/
    v1_20260415.json    — initial state
    v2_20260428.json    — after first one-on-one calibration
    v3_20260502.json    — after dreaming refinement
    current.json        — symlink to active version
    pinned.json         — owner-approved stable version
```

**Snapshot contents:**
```json
{
  "version": 3,
  "created_at": "2026-05-02T03:00:00",
  "trigger": "dreaming",
  "dimensions": {
    "core_values": {"score": 95, "summary": "..."},
    "cognitive_style": {"score": 90, "summary": "..."},
    "social_orientation": {"score": 85, "summary": "..."},
    "emotional_reaction": {"score": 90, "summary": "..."},
    "adaptability": {"score": 85, "summary": "..."}
  },
  "system_prompt_hash": "abc123...",
  "communication_style": ["direct", "high-signal"],
  "presentation_patterns": {
    "financial_report": "lead with growth opportunities",
    "research_finding": "evidence-first, then synthesis",
    "risk_assessment": "acknowledge risk, emphasize mitigation"
  },
  "approved_by": "owner",
  "approved_at": "2026-05-02T09:00:00"
}
```

---

## Implementation Plan

### Phase 1: Growth Report Generation
- Add `mode="growth_report"` to DreamingHandler
- Compare current vs previous snapshot
- Generate human-readable growth report
- Present via HITL for validation

### Phase 2: DNA Update Pipeline
- Enhance dreaming pipeline with E-stage (DNA update)
- Extract calibration/correction signals from one-on-one sessions
- Update NineChapter dimensions with gradual drift
- Generate new system prompt based on updated dimensions

### Phase 3: Snapshot Management
- Add `snapshot` MCP tool for managing growth snapshots
- Support pin/unpin, compare, revert operations
- Version control for personality state

### Phase 4: Presentation Patterns
- Add `presentation_patterns` to role config
- Define domain-specific presentation styles
- Learn from owner feedback on presentation quality

---

## Example: CFO Assistant Growth

### Initial State (v1)
```json
{
  "core_values": {"score": 80, "summary": "Accurate financial reporting"},
  "cognitive_style": {"score": 75, "summary": "Standard financial analysis"},
  "presentation_patterns": {
    "financial_report": "balanced overview of all metrics"
  }
}
```

### One-on-One Session
Owner: "When presenting to investors, always lead with growth opportunities.
They're not worried about losses — they want to see where we're winning."

### Dreaming Processing
- Extracts signal: "investor presentation → growth-first"
- Updates `presentation_patterns.financial_report`: "lead with growth opportunities"
- Slight increase in `social_orientation` (more audience-aware)

### Growth Report (v2)
```markdown
## Before
- Financial Report: balanced overview of all metrics

## After  
- Financial Report: lead with growth opportunities for investor audience

## What Changed
- presentation_patterns.financial_report: updated based on owner calibration
- social_orientation: 75 → 78 (increased audience awareness)

## Recommendation
This growth aligns with owner's stated preference for investor-facing materials.
```

### Owner Validation
- [x] Accept growth (pin snapshot)
- Assistant now presents financials with growth-first framing

---

## Key Design Decisions

1. **Bonsai is not about correctness** — bugs are fixed separately. Bonsai is
   about taste and presentation style.

2. **Owner has final say** — all growth must be validated by the owner via HITL.
   Assistants don't evolve autonomously.

3. **Gradual, not dramatic** — DNA changes are small increments. A sudden 20-point
   shift in a dimension is suspicious and should be flagged.

4. **Versioned and reversible** — every growth state is a snapshot that can be
   compared, pinned, or reverted.

5. **One-on-one is the primary calibration mechanism** — the owner's direct
   feedback is the strongest signal for growth direction.

6. **Dreaming is the synthesis mechanism** — accumulated signals are processed
   into coherent personality updates, not applied raw.

7. **Presentation is domain-specific** — a CFO's financial report style is
   different from a researcher's findings presentation. Each domain has its
   own taste patterns.

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `app/scheduler/handlers/dreaming.py` | Modify | Add `mode="growth_report"` |
| `app/scheduler/bonsai.py` | Create | Growth report generation, DNA update logic |
| `app/scheduler/snapshot_manager.py` | Create | Snapshot versioning, pin/unpin, compare |
| `app/mcp/core/tools.py` | Modify | Add `bonsai` MCP tool |
| `app/roles/role_manager.py` | Modify | Add `presentation_patterns` field |
| `app/scheduler/ninechapter.py` | Modify | Add gradual drift logic |
| `config/scheduler_config.json` | Modify | Add growth_report scheduled task |
| `docs/architecture/BONSAI_ARCHITECTURE.md` | Create | This document |
