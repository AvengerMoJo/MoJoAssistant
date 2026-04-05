# Spec: Context Budget Guard — v1.2.15

## Problem

The agentic executor accumulates messages across iterations with no awareness of the
model's context window. Three fields exist in `llm_config.json`:

- `context_limit` — total context window (tokens)
- `output_limit` — max output tokens (used ✅)
- No `input_limit` field

Only `output_limit` is read. `context_limit` is stored but never used. The executor
sends the full message history to every LLM call regardless of size.

### Practical consequences

- **Silent overflow**: LMStudio / llama.cpp silently truncates the oldest messages when
  the prompt exceeds the context window. The model loses its goal, tool results, or
  reasoning history mid-task without the executor knowing.
- **Confused behaviour**: If the system prompt or goal is truncated, the model drifts —
  produces unrelated output, repeats tool calls, or fails to write FINAL_ANSWER.
- **OpenRouter input limits**: Free-tier models often have asymmetric limits (e.g. 8k
  input, 2k output, 131k total). No `input_limit` field means we can't guard against
  per-request input caps separately from total context.

## Desired Behaviour

Before each LLM call in the executor:

1. **Estimate** the token count of the full message list (fast approximation, no API call)
2. **Compare** against `context_limit - output_limit` (the input budget)
3. If approaching the limit: **trim** the oldest non-essential messages to stay within budget
4. Log when trimming occurs so it's visible in iteration metrics
5. Never trim: system prompt, first user message (the goal), most recent assistant turn

## Token Estimation

No tokeniser dependency — use character count with a conservative ratio:

```python
def _estimate_tokens(messages: list[dict]) -> int:
    """Fast token estimate: ~4 chars per token, +10 overhead per message."""
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        total += len(str(content)) // 4 + 10
        # Tool calls add structured JSON overhead
        for tc in m.get("tool_calls", []):
            total += len(json.dumps(tc)) // 4 + 5
    return total
```

Conservative (underestimates slightly for CJK, overestimates for code). Safe direction:
better to trim a little early than overflow.

## Trimming Strategy

Protected messages (never removed):
- `messages[0]` — system prompt
- `messages[1]` — first user message (the goal)
- Last 4 messages — recent context the model needs

Trimmable: everything in between — older tool results, intermediate reasoning turns.

```python
def _trim_to_context_budget(
    messages: list[dict],
    context_limit: int,
    output_limit: int,
    safety_margin: float = 0.85,
) -> tuple[list[dict], bool]:
    """
    Trim middle messages until estimated tokens fit within input budget.
    Returns (trimmed_messages, was_trimmed).

    Budget = (context_limit - output_limit) * safety_margin
    """
    input_budget = int((context_limit - output_limit) * safety_margin)
    if _estimate_tokens(messages) <= input_budget:
        return messages, False

    protected_head = messages[:2]   # system + goal
    protected_tail = messages[-4:]  # recent context
    trimmable = messages[2:-4]

    # Drop from the oldest end first
    while trimmable and _estimate_tokens(protected_head + trimmable + protected_tail) > input_budget:
        trimmable.pop(0)

    trimmed = protected_head + trimmable + protected_tail
    return trimmed, True
```

## Config Changes

Add `input_limit` as an optional field to resource entries:

```json
{
  "lmstudio": {
    "context_limit": 32768,
    "output_limit": 8192,
    "input_limit": null
  },
  "openrouter_free": {
    "context_limit": 131072,
    "output_limit": 8192,
    "input_limit": 8192
  }
}
```

When `input_limit` is set, use it directly as the input budget instead of
`context_limit - output_limit`.

## Executor Integration

In `agentic_executor.py`, before each `self._llm.complete(messages, ...)` call:

```python
context_limit = resource_config.get("context_limit", 32768)
output_limit  = resource_config.get("output_limit", 8192)
input_limit   = resource_config.get("input_limit")  # None = derive from context

messages, was_trimmed = _trim_to_context_budget(
    messages,
    context_limit=input_limit or context_limit,
    output_limit=output_limit if not input_limit else 0,
)
if was_trimmed:
    self._log(
        f"Context trim: history reduced to fit {context_limit}t window",
        "warning",
    )
    iter_metadata["context_trimmed"] = True
```

## Metrics

Add to `iteration_log` entries:
- `estimated_input_tokens: int` — estimated tokens sent
- `context_trimmed: bool` — whether trimming occurred this iteration

Add to task-level metrics:
- `total_context_trims: int` — how many times trimming fired across all iterations

## Success Criteria

1. A 25-iteration Carl task on a 32k context model no longer silently loses its goal
   mid-task
2. `iteration_log` shows `estimated_input_tokens` growing per iteration and
   `context_trimmed: true` when it fires
3. Tasks that previously drifted or repeated tool calls stabilise after trimming

## Open Questions

- **Trim vs summarise**: Dropping old messages loses information. A smarter approach
  would summarise dropped turns into a single "progress so far" message. Deferred to
  v1.3.x — trimming is safe enough for now and requires no LLM call.
- **Tool result size**: Large bash_exec outputs (e.g. `cat bigfile.py`) are the biggest
  context consumers. A per-tool output cap (e.g. 2000 chars) would be more surgical.
  Already partially addressed by `search_memory` truncation. Generalise in v1.2.15.
