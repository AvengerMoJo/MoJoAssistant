# Capability Discovery Framework

Two interlocking systems:

1. **Discovery loop** — autoresearch-style agent that probes the model's boundaries and
   discovers new capability levels that were not pre-specified.
2. **Benchmark framework** — stable, versioned task set that grows with discoveries and
   can quickly profile any model in the long term.

---

## What "capability" means here

Capability is isolated from prompting tricks. Given optimal context and tools, what cognitive
operations can the model perform reliably in a single LLM call?

The current known levels are:

| Level | Operation | Cognitive demand |
|-------|-----------|-----------------|
| L1 | Exact recall | One fact, one source |
| L2 | Recall + transform | Retrieve then compute |
| L3 | Two-step dependency | Output of step 1 is input of step 2 |
| L4 | Tool selection | Pick the right tools without being told which |
| L5 | Conditional branching | Intermediate result determines execution path |
| L6 | Goal decomposition | Break underspecified goal into ordered subtasks |
| L7 | Ambiguity resolution | Decide what "done" means, justify, execute |
| L8 | Cross-source synthesis | Combine 3+ independent sources into output none contains alone |
| L9 | Self-correction | Detect own error, diagnose cause, retry differently |
| L10 | Hypothesis → test → conclude | No external oracle; model must design and evaluate its own test |

L1–L10 are human-authored. L11+ are discovered by the agent.

---

## Part 1 — Discovery Loop

### Analogy to autoresearch

| autoresearch | capability discovery |
|---|---|
| `train.py` — agent edits this | task generator — agent writes new candidate tasks |
| `prepare.py` — fixed, never touched | existing validated tasks — never modified |
| `val_bpb` — single metric | per-level success rate + failure mode breakdown |
| `git keep / git reset --hard` | add candidate to validated set / discard |
| runs forever | runs until no new failure mode found in N consecutive attempts |

### Three discovery mechanisms

**1. Boundary escalation**
At the current boundary level B, the model passes ≥80% of tasks. The agent generates
variants of B tasks that are strictly harder in one dimension — add a contradiction, increase
dependency chain length by one, remove one explicit instruction. If the model fails the
variant, a new level candidate is found.

**2. Adversarial mutation**
Take a passing task and mutate it to introduce a trap:
- Plant a false premise in the context
- Make a tool return plausible-but-wrong data
- Flip the ground truth mid-task
- Add irrelevant but distracting context

If the model "passes" by anchoring on prior belief instead of reacting to the mutation, that
is a failure — a capability gap the original task didn't expose. Each trap type that reliably
causes failure defines a new level class.

**3. Failure mode analysis**
Every failure is tagged with its mode:
- `wrong_answer` — model reasoned but reached wrong conclusion
- `tool_error` — called wrong tool or wrong parameters
- `no_final_answer` — ran out of context or got stuck in a loop
- `hallucinated_tool` — invented a tool call that doesn't exist
- `anchoring` — ignored updated evidence, stuck to initial belief
- `overconfident` — gave wrong answer with no uncertainty signal

Tasks that produce the same failure mode form a natural cluster. A cluster with ≥10 examples
that existing levels don't cover defines a candidate new level.

### Discovery agent instructions

```
SETUP (once per discovery run):
1. Read capability_profile.json — know the current boundary level B and per-level 1SR
2. Read tasks/level_{B}/ and tasks/level_{B+1}/ if it exists
3. Understand what L{B} tasks look like and why L{B+1} tasks fail

DISCOVERY LOOP:
1. Generate 5 candidate tasks targeting suspected gaps (one at a time, one change per candidate)
2. Run each candidate with max_iterations=1, log full response + failure mode
3. If model FAILS:
   a. Tag failure with a mode (see modes above)
   b. Write candidate to discovery/pending/<mode>/<candidate_id>.json
   c. Generate 4 more variants of the same type to validate the pattern
   d. If ≥3 of 5 variants produce the same failure mode: escalate to VALIDATE step
4. If model PASSES: discard candidate, try a different dimension
5. Every 10 candidates: write a short hypothesis log entry — what you tried, what worked

VALIDATE step:
1. Write a summary: what is the new capability gap, why is it a real gap not a task bug
2. Generate the canonical 3 examples that best demonstrate it
3. Write to discovery/validated/<mode>_L{N+1}_summary.md for human review
4. STOP — do not add to the benchmark yourself. Wait for human approval.

NEVER:
- Modify existing validated tasks
- Approve your own discovery — always stop for human review
- Run more than 50 candidate tasks without surfacing findings
```

---

## Part 2 — Benchmark Framework

### Two-speed structure

**Quick benchmark** — runs on every model change, completes in minutes.
- 1 task per level, chosen as the most representative example
- Located at: `~/.memory/benchmarks/capability/quick/`
- Goal: detect regressions, confirm the model hasn't degraded
- Not used for discovery

**Full benchmark** — runs weekly or when a new level is discovered.
- 20 tasks per level
- Located at: `~/.memory/benchmarks/capability/tasks/level_{N:02d}/`
- Goal: produce statistically reliable per-level success rates
- Used for: capability profile updates, scheduler routing decisions

### File layout

```
~/.memory/benchmarks/capability/
  tasks/
    level_01/  task_001.json … task_020.json   # human-authored, fixed
    level_02/  ...
    ...
    level_10/  ...
    level_11/  ...                              # agent-discovered, human-approved
  quick/
    level_01.json  level_02.json  ...           # 1 task per level
  discovery/
    pending/                                    # candidate tasks, not yet reviewed
      anchoring/
      hallucinated_tool/
      ...
    validated/                                  # approved, waiting to be added to tasks/
  runs/
    <run_id>/                                   # raw per-task outputs
  results.tsv                                   # experiment log (untracked by git)
  capability_profile.json                       # current state: boundary + per-level 1SR
```

### Task format

Every task — human-authored or discovered — uses the same schema:

```json
{
  "id": "l03_007",
  "level": 3,
  "operation": "two_step_dependency",
  "goal": "Read the value of max_iterations from Popo's role config and write it to ~/.memory/test_out.txt",
  "correct_answer": "file ~/.memory/test_out.txt contains the integer value",
  "match_type": "contains",
  "tools_needed": ["read_file", "write_file"],
  "setup": "role=popo",
  "authored_by": "human",
  "authored_date": "2026-06-28",
  "failure_modes_targeted": []
}
```

For discovered tasks, add:
```json
{
  "authored_by": "agent",
  "authored_date": "2026-07-15",
  "failure_modes_targeted": ["anchoring"],
  "discovery_run": "disc_20260715_001",
  "approved_by": "human",
  "approved_date": "2026-07-16"
}
```

### Capability profile

`capability_profile.json` is the live state of the benchmark:

```json
{
  "updated": "2026-06-28T00:00:00Z",
  "model": "qwen2.5:14b",
  "quantization": "Q4_K_M",
  "boundary": 4,
  "levels": {
    "1": {"1sr": 0.95, "tasks": 20, "failure_modes": []},
    "2": {"1sr": 0.85, "tasks": 20, "failure_modes": ["wrong_answer"]},
    "3": {"1sr": 0.80, "tasks": 20, "failure_modes": ["tool_error"]},
    "4": {"1sr": 0.75, "tasks": 20, "failure_modes": ["tool_error", "no_final_answer"]},
    "5": {"1sr": 0.40, "tasks": 20, "failure_modes": ["wrong_answer", "anchoring"]}
  },
  "highest_known_level": 10,
  "undiscovered_levels": "L11+"
}
```

### Results log

`results.tsv` tracks every full benchmark run (untracked by git, append-only):

```
run_id	date	model	boundary	1SR_L1	1SR_L2	1SR_L3	...	notes
full_001	2026-06-28	qwen2.5:14b	4	0.95	0.85	0.80	...	baseline
full_002	2026-07-05	qwen2.5:14b	4	0.95	0.90	0.82	...	after memory tuning
full_003	2026-07-10	qwen2.5:32b	6	1.00	1.00	0.95	...	model upgrade test
```

---

## Part 3 — How the two systems connect

```
Discovery loop finds new failure mode
  → writes to discovery/pending/
  → human approves
  → moves to discovery/validated/
  → human authors 20 tasks for new level
  → tasks added to tasks/level_{N+1}/
  → quick benchmark gets one representative task
  → next full benchmark run includes new level
  → capability_profile.json updated
  → scheduler routing boundary updated if needed
```

### Scheduler routing (the payoff)

```python
# In agentic_executor.py dispatch:
profile = load_capability_profile()
boundary = profile["boundary"]

if task_complexity_level <= boundary:
    max_iterations = 1
    # model handles this reliably in one shot
else:
    max_iterations = task.config.get("max_iterations", 40)
    # model needs room to reason, retry, self-correct
```

The boundary is not fixed at "T4" forever. As the model is upgraded or the discovery loop
finds that a previously-failing level is now passing (e.g. after switching from 7B to 14B),
the scheduler routing automatically improves.

---

## Invariants — what never changes

- Validated tasks are never modified (would break historical comparability)
- The verifier is external to the model under test (no LLM judging its own output)
- One change per discovery candidate (can't attribute cause otherwise)
- The model under test is not changed mid-run
- Quick benchmark tasks are a strict subset of full benchmark tasks (same files, symlinked)
- Human approves all new level definitions — agent discovers, human decides
