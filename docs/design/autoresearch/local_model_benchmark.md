# Local Model Benchmark — 1-Shot Complexity Ceiling

**Research question:** What is the maximum task complexity where the local model (Qwen) succeeds
in exactly 1 LLM call — correct answer, no retry, no follow-up iteration?

**Goal:** Find the empirical complexity boundary so the scheduler can route tasks intelligently:
below the boundary → dispatch with `max_iterations=1` (save compute);
above the boundary → dispatch with a full iteration budget (don't starve).

---

## Autoresearch Analogy

| autoresearch | this research |
|---|---|
| `prepare.py` — fixed eval harness | benchmark task set + scoring (do not modify) |
| `train.py` — mutable experiment surface | prompt template config (context depth, tool list, phrasing) |
| `val_bpb` — single objective metric | 1-shot success rate per complexity tier |
| agent edits `train.py`, runs, compares | agent edits prompt config, runs batch, reads scores |
| `git keep / git reset --hard` | keep config if 1-shot rate improved, revert if not |
| 5-min fixed budget | fixed batch size per experiment run |

The agent is the experimenter. It reads scores, forms a hypothesis, edits the prompt config,
re-runs the batch, compares, keeps or reverts — indefinitely.

---

## Complexity Tiers (fixed, do not change mid-experiment)

Each tier has 20 tasks. Tasks are fixed for the lifetime of the benchmark — changing them
invalidates comparisons across experiment runs.

| Tier | Name | Description | Example |
|------|------|-------------|---------|
| T1 | Single lookup | Read one resource, answer directly | "What is Popo's current temperature setting?" |
| T2 | Two-step | Read + compute or transform | "How many tasks did Rebecca complete last week? Sum from task history." |
| T3 | Multi-tool | Coordinate 3+ tools in sequence | "Search memory, read a file, write a summary to knowledge base" |
| T4 | Ambiguous spec | Incomplete goal — must decide and justify | "Improve the dreaming config" (no success criteria given) |
| T5 | Cross-domain synthesis | Combine knowledge from 2+ unrelated domains | "Given memory architecture and recent task failures, propose a fix" |

**Total:** 100 tasks across 5 tiers (20 per tier).

---

## Metric: 1-Shot Success Rate (1SR)

For each task:
- **Success**: model produces a valid `FINAL_ANSWER` on iteration 1, and the answer matches
  the known-correct output (exact match or semantic match judged by a lightweight verifier).
- **Failure**: task takes >1 iteration, crashes, times out, or produces wrong answer on iteration 1.

Per-tier score: `1SR(Tx) = successes / 20`

**Primary metric**: `1SR(T_boundary)` — the highest tier where `1SR ≥ 0.80`.

Secondary metrics logged per experiment:
- Mean iterations to completion per tier (even for failures)
- Failure mode breakdown: wrong answer / timeout / tool error / no FINAL_ANSWER

---

## Experiment Surface (the "train.py" equivalent)

The agent may only modify `benchmark_config.json`. Everything else is fixed.

```json
{
  "context_depth": 5,
  "pre_granted_tools": ["read_file", "memory_search"],
  "goal_phrasing": "concrete",
  "few_shot_examples": 0,
  "memory_injection": true,
  "max_context_tokens": 2000
}
```

**Tunable fields:**

| Field | Type | Range | Description |
|-------|------|--------|-------------|
| `context_depth` | int | 1–20 | How many memory results injected into system prompt |
| `pre_granted_tools` | list | subset of all tools | Tools available without asking |
| `goal_phrasing` | enum | `concrete`, `vague`, `structured` | How specifically the task goal is phrased |
| `few_shot_examples` | int | 0–3 | Examples of completed tasks prepended to prompt |
| `memory_injection` | bool | true/false | Whether role memory context is included |
| `max_context_tokens` | int | 500–4000 | Token budget for injected context |

**Immutable (do not touch):**
- The 100 benchmark tasks themselves
- The scoring function (exact match / semantic match verifier)
- The model being tested (local Qwen — no switching to external API)
- `max_iterations` cap of 1 for 1-shot measurement
- The local model endpoint URL

---

## File Layout

```
docs/design/autoresearch/
  local_model_benchmark.md         — this spec (human edits)
  benchmark_config.json            — experiment surface (agent edits)
  results.tsv                      — experiment log (untracked by git)

~/.memory/benchmarks/local_model/
  tasks/
    tier1/  task_001.json … task_020.json
    tier2/  task_001.json … task_020.json
    tier3/  ...
    tier4/  ...
    tier5/  ...
  runs/
    <run_id>/  raw outputs per task
```

---

## Task Format

Each task file in `~/.memory/benchmarks/local_model/tasks/tierN/`:

```json
{
  "id": "t1_001",
  "tier": 1,
  "goal": "What is Popo's current temperature setting?",
  "correct_answer": "0.7",
  "match_type": "exact",
  "tools_needed": ["read_file"],
  "setup": "role=popo"
}
```

`match_type`:
- `exact` — string equality after stripping whitespace
- `semantic` — verifier LLM judges if meaning matches (used for T4/T5)
- `contains` — correct_answer is a substring of the response

---

## Experiment Loop (agent instructions)

```
SETUP (once):
1. Read this file and benchmark_config.json
2. Confirm task files exist in ~/.memory/benchmarks/local_model/tasks/
3. Create results.tsv with header: run_id \t config_hash \t 1SR_T1 \t 1SR_T2 \t 1SR_T3 \t 1SR_T4 \t 1SR_T5 \t boundary \t notes
4. Run the baseline (benchmark_config.json as-is), record results

LOOP FOREVER:
1. Read results.tsv — understand current best boundary tier and which tiers are weakest
2. Form a hypothesis: "T3 1SR is 0.65 because tools aren't pre-granted — try adding knowledge_search"
3. Edit benchmark_config.json with ONE change
4. git commit benchmark_config.json with a description of the hypothesis
5. Run the benchmark batch (all 100 tasks, max_iterations=1)
6. Read the scores
7. If boundary improved (or same tier but higher 1SR): keep the commit
8. If boundary regressed: git reset --hard, log "discard" in results.tsv
9. Log to results.tsv: run_id, config_hash, per-tier 1SR, boundary, short description
```

**One change per experiment.** Don't change two fields at once — you won't know which one caused the effect.

---

## Success Criteria for the Research

The research is complete when either:
1. **Boundary is found**: `1SR(Tx) ≥ 0.80` and `1SR(Tx+1) < 0.50` — clear cliff identified
2. **Ceiling confirmed**: `1SR(T5) ≥ 0.80` — local model handles all tiers in 1 shot (unlikely but possible)
3. **Floor confirmed**: `1SR(T1) < 0.80` — model can't reliably do even T1 in 1 shot (prompt engineering needed first)

The boundary tier feeds directly into the scheduler's routing logic:
```python
# In agentic_executor.py dispatch:
if task_complexity_tier <= LOCAL_MODEL_1SHOT_BOUNDARY:
    max_iterations = 1
    model = "local"
else:
    max_iterations = task.config.get("max_iterations", 40)
    model = task.config.get("model_preference", "local")
```

---

## What NOT to do

- Do not change the benchmark tasks mid-experiment — it breaks comparability across runs
- Do not switch the model under test — this benchmark is specifically for local Qwen
- Do not judge success subjectively — use the verifier, not intuition
- Do not run partial batches — always run all 100 tasks so tier scores are comparable
- Do not change two config fields in one experiment — you lose the ability to attribute cause
