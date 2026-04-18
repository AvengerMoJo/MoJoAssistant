# LOCOMO Benchmark Workflow

## Concept Mapping

| LOCOMO | MoJo | Notes |
|--------|------|-------|
| Dialogue | Two people's relationship | 10 dialogues = 10 speaker pairs |
| **Session** | **One conversation in Ben's memory** | 272 sessions, stored once, permanent |
| Turn | One fact in role-scoped knowledge | 5,882 turns total, ~181K tokens |

Sessions are the atomic unit of memory. Once stored they never change.
This is not a dataset — it is Ben's lived conversation history.

## Benchmark Role: `ben`

Ben is a dedicated benchmark role whose memory contains the full LOCOMO dataset.
He must never be used for other purposes, and his memory must not be reset
unless deliberately re-running the setup from scratch.

## Dataset

- Source: `locomo10.json` (cloned from https://github.com/snap-research/locomo)
- Local path: `/tmp/locomo/data/locomo10.json`
- 10 dialogues, 272 sessions, 5,882 turns, 1,986 QA pairs

## Phase 1 — Setup (one-time, permanent)

**Status: COMPLETE as of 2026-04-18**

```bash
venv/bin/python tests/benchmarks/run_locomo_role_memory.py \
  --data-dir /tmp/locomo/data \
  --role-id ben --setup-only --variant facts_plus_abcd \
  --quality-level good
```

What was built:
- 272 sessions ingested into `~/.memory/roles/ben/` (session-level dedup via `locomo_ingested_sessions.json`)
- 272 ABCD archives built at `~/.memory/roles/ben/dreams/locomo_d{d}_s{s}/archive_v1.json`
- Quality level: `good` (includes `key_facts` extraction per B chunk and C cluster)

Re-running setup is safe — already-ingested sessions and existing dream archives are skipped automatically.
Only use `--reset-role-memory` if you need to start completely from scratch.

## Phase 2 — Evaluation (repeatable, fast)

**Status: READY TO RUN**

```bash
# facts + ABCD combined (primary benchmark)
venv/bin/python tests/benchmarks/run_locomo_role_memory.py \
  --data-dir /tmp/locomo/data \
  --role-id ben --eval-only --variant facts_plus_abcd \
  --output results/locomo_ben_v2_full_facts_plus_abcd.jsonl

# facts only (ablation)
venv/bin/python tests/benchmarks/run_locomo_role_memory.py \
  --data-dir /tmp/locomo/data \
  --role-id ben --eval-only --variant facts_only \
  --output results/locomo_ben_v2_full_facts_only.jsonl

# ABCD only (ablation)
venv/bin/python tests/benchmarks/run_locomo_role_memory.py \
  --data-dir /tmp/locomo/data \
  --role-id ben --eval-only --variant abcd_only \
  --output results/locomo_ben_v2_full_abcd_only.jsonl
```

Phase 2 does not touch Ben's memory. It only reads from existing knowledge and dream archives.

## Scoring

Token F1 uses SQuAD-standard normalization (lowercase + strip punctuation + Counter overlap).
The old implementation was missing punctuation stripping, which penalized correct verbose
answers (e.g. "Sweden." scoring 0.0 against "Sweden").

### Baseline results (d00 only, 199 questions, pre-fix scoring)

| Variant | Old F1 | Fixed F1 |
|---------|--------|----------|
| facts_only | 0.170 | 0.257 |
| facts_plus_abcd | 0.190 | 0.279 |
| abcd_only | 0.141 | 0.196 |

Full 10-dialogue results pending Phase 2.

### Category breakdown (facts_only, d00, fixed scoring)

| Category | F1 |
|----------|-----|
| single-hop | 0.125 |
| multi-hop | 0.351 |
| temporal | 0.062 |
| commonsense | 0.303 |
| adversarial abstention | 83% |

Temporal is lowest due to relative dates stored in conversation facts
("last year", "yesterday") vs absolute ground truth ("2022", "7 May 2023").
The answer prompt now includes explicit date resolution instructions.

## Key Improvements in v2 (applied before Phase 2)

1. **`token_f1` fix** — punctuation normalization, Counter-based overlap
2. **ABCD `key_facts`** — chunker and synthesizer now extract atomic factual statements;
   `retrieve_abcd` prefers `key_facts` over raw content when available
3. **Date resolution** — answer prompt instructs the model to resolve relative dates
4. **Retrieval tuning** — `facts_top_k` 12→20, `top_c` 6→15
5. **Session-level dedup** — persistent memory, never re-ingests existing sessions

## Notes

- `--judge` flag enables LLM judge scoring (more meaningful than token F1 for verbose answers, but slow)
- The `ben` role's dream archives were built with `--quality-level good`, which runs two LLM passes per session (chunker + synthesizer) and extracts `key_facts`
- Dreaming archives built before the `key_facts` prompt change will not have `key_facts`; `retrieve_abcd` falls back to raw content for those
