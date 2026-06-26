# Spec: Post-Write FINAL_ANSWER Nudge

## Problem

Rebecca (and any role doing long-form research) consistently writes a file
successfully but times out before emitting `<FINAL_ANSWER>`. The scheduler
marks the task `failed`. The output artifact exists and is complete, but
it's invisible to the caller.

This causes two cascading failures:

1. The dashboard shows `failed` with no link to the artifact.
2. The caller (user or Paul) re-dispatches the task, wasting resources on
   work already done.

Real example: task `756c2bea` — Rebecca wrote the AgentAuditor report in
iteration 3 (250s of generation + `write_file`). The next LLM call to
produce `<FINAL_ANSWER>` timed out. Task retried 3 times. Report was there
the whole time.

## Root Cause

The agentic executor loop in `app/scheduler/agentic_executor.py` (around
line 1449) collects tool results, appends them to `messages`, then
immediately calls `continue` to fire another LLM call. No signal is given
to the LLM that writing a file is typically the *last* action — it treats
the tool result as just another step and starts generating a fresh full
response. When that generation is long (reasoning tokens + report recap),
the session times out before `<FINAL_ANSWER>` is emitted.

The loop already has one injection pattern: `NEAR_LIMIT_PROMPT` fires when
`iteration >= max_iterations - 1`. The fix follows the same pattern.

## Proposed Fix

After appending tool results to `messages`, detect whether a write-type tool
just succeeded. If yes — and no `<FINAL_ANSWER>` has been produced yet —
inject a short wrap-up nudge before the next LLM call.

### Trigger conditions (all must be true)

1. The last tool call set contained a write-type tool (`write_file`,
   `write_knowledge`, or any tool whose name ends in `_write` or
   `write_file`).
2. At least one of those calls returned a success result (content contains
   `"success": true` or `"Wrote"`).
3. No `<FINAL_ANSWER>` has been produced yet in this session.
4. The `NEAR_LIMIT_PROMPT` has not already been injected this iteration
   (avoid double-injecting conflicting prompts).

### Message to inject

```
The file was written successfully. Your main work is complete.
Emit <FINAL_ANSWER> now with a brief confirmation of what you wrote and
where. Do not call any more tools.
```

### Where in the code

`app/scheduler/agentic_executor.py`, immediately after the loop-detection
block (after line ~1516), before the `continue` that drives the next
iteration:

```python
# Post-write wrap-up nudge: if the last tool call wrote a file and we
# have no FINAL_ANSWER yet, prompt the model to wrap up now instead of
# starting another generation cycle.
_WRITE_TOOLS = {"write_file", "write_knowledge"}
_last_tool_names = {tc["function"]["name"] for tc in tool_calls}
if _last_tool_names & _WRITE_TOOLS and not final_answer:
    _write_result_ok = any(
        '"success": true' in r or "Wrote" in r
        for r in tool_results
    )
    if _write_result_ok and iteration < max_iterations - 1:
        _nudge = (
            "The file was written successfully. Your main work is complete.\n"
            "Emit <FINAL_ANSWER> now with a brief confirmation of what you "
            "wrote and where. Do not call any more tools."
        )
        messages.append({"role": "user", "content": _nudge})
        self._record(task.id, "user", _nudge, iteration=abs_iteration)
```

The `iteration < max_iterations - 1` guard prevents double-injection with
`NEAR_LIMIT_PROMPT` on the penultimate iteration.

## What We Do NOT Change

- No new config field (`max_duration_seconds` is not the issue).
- No role-specific prompt changes.
- No retry logic changes.
- No changes to `max_iterations`.
- The nudge does not fire for non-write tool calls (bash_exec, memory_search,
  etc.) — only file writes.

## Scope Risk: Mid-Task Writes

Some tasks write intermediate files (e.g. save partial results, then
continue processing). The nudge would fire too early for those.

Mitigation: the nudge says "do not call any more tools" but does not force
termination. If the LLM has more work to do, it can ignore the nudge and
continue — the executor does not enforce it. The nudge is advisory, not a
hard stop.

If mid-task writes become a real problem, we can add an opt-out flag in the
task config (`"final_write_nudge": false`) or restrict the nudge to the last
N iterations only.

## Verification

Use the benchmark we built today:

```bash
venv/bin/python tests/benchmarks/llm_compliance_runner.py --all
```

The `write_large_then_answer` test case with `max_iter_after_tool=1` will
fail before the fix and pass after. The `characterization_protocol` suite in
the eval framework (`doctor_eval_run suite=characterization_protocol`) gives
the same signal with per-resource history.

## Implementation Size

~10 lines added to `app/scheduler/agentic_executor.py`.
No new files. No schema changes. No config changes.

## Acceptance Criteria

1. `write_large_then_answer` passes for local Qwen on the compliance runner.
2. Rebecca's AgentAuditor-style task completes in a single attempt with
   status `completed` (not `failed` + artifact present).
3. No regression on existing smoke/eval suites — tasks with intermediate
   writes still run to completion.
