# Qwen3.5 Tool Calling — Know-How & Debugging Guide

## Context

MoJoAssistant uses Qwen3.5-35B-A3B served via LMStudio (OpenAI-compatible API at
`http://localhost:8080/v1`). This document captures lessons learned debugging tool
calling failures with this model and template.

---

## How to Read the Chat Template as a Debugging Reference

Even when you are **not** using llama-server directly, the model's Jinja2 chat
template (`chat_template.jinja`) is the ground truth for how the model expects
its conversation to be structured. Always fetch and read it when debugging
unexpected model behaviour.

```
https://huggingface.co/Qwen/Qwen3.5-35B-A3B/raw/main/chat_template.jinja
```

The template tells you:
- What format tool definitions are injected in (system message, raw JSON inside `<tools>` tags)
- What format tool calls are rendered as (`<tool_call><function=name><parameter=x>val</parameter></function></tool_call>`)
- What format tool responses are rendered as (`<tool_response>...</tool_response>` inside a user turn)
- Whether the model uses thinking tokens (`<think>...</think>`) and when

LMStudio with the OpenAI-compatible API handles all format conversion transparently —
you never send XML tool calls, you use standard `tool_calls` JSON. But the template
tells you what the model *sees internally*, which explains why it behaves as it does.

---

## Known Issues & Fixes

### 1. `|items` filter bug — corrupted tool argument history

**Symptom:** Model calls a tool on iteration 1 correctly, then on iteration 2+ loses
confidence and produces a planning-style final answer without calling further tools.
Or: model sees its own previous tool calls but behaves as if the arguments were empty.

**Root cause:** The original `chat_template.jinja` uses:
```jinja
{%- for args_name, args_value in tool_call.arguments|items %}
```
The `|items` filter is non-standard Jinja2. When it fails silently, tool call argument
blocks are omitted from the rendered conversation history. The model sees:
```
<tool_call>
<function=bash_exec>
</function>
</tool_call>
```
instead of:
```
<tool_call>
<function=bash_exec>
<parameter=command>
ls /tmp
</parameter>
</function>
</tool_call>
```
Corrupted context → model confusion → premature exit.

**Fix (llama-server side):** Replace `|items` iteration with a mapping check + key loop:
```jinja
{%- if tool_call.arguments is mapping %}
    {%- for args_name in tool_call.arguments %}
        {%- set args_value = tool_call.arguments[args_name] %}
        ...
    {%- endfor %}
{%- endif %}
```
See `fix_and_test_template.py` in the project root for the automated patch script.

**Note:** This only affects llama.cpp/llama-server deployments. LMStudio uses its own
tool call handling and may not be affected by this specific template bug.

---

### 2. `<think>` tokens leaking into response content

**Symptom:** `_parse_final_answer` extracts content from inside a `<think>` block, or
`requires_tool_use` logic fires incorrectly because `response_text` contains planning
inside `<think>` tags.

**Root cause:** Qwen3.5 is a thinking model. The template unconditionally injects
`<think>\n` at generation time. Older llama.cpp builds and some LMStudio versions
do not strip `<think>...</think>` from the `content` field, leaking reasoning tokens
into the response the executor parses.

**Fix (executor side):** Strip think blocks from `response_text` before any parsing:
```python
response_text = re.sub(r"<think>.*?</think>", "", response_text, flags=re.DOTALL).strip()
```
This is applied in `app/scheduler/agentic_executor.py` immediately after reading
`message["content"]`.

With a current LMStudio build and `--jinja` flag, the server separates thinking tokens
into `reasoning_content` and puts the actual response in `content`. The executor
already has a fallback: `message.get("content") or message.get("reasoning_content")`.

---

### 3. Missing task ID — null ID crash

**Symptom:** Task is created with `id: null`. Executor crashes immediately with
`'NoneType' object has no attribute 'replace'` (in `session_storage.py`).

**Root cause:** `_execute_scheduler_add_task` in `tools.py` called
`args.get("task_id")` with no fallback. When no `task_id` was provided by the caller,
`None` was passed to `Task(id=None, ...)`.

**Fix:** Auto-generate a short UUID when `task_id` is absent:
```python
task_id = args.get("task_id") or args.get("id")
if not task_id:
    task_id = str(uuid.uuid4())[:8]
```

---

## Tool Calling Format — What Works

| Layer | Format |
|---|---|
| Tool definitions sent to API | Standard OpenAI `tools` array (JSON schema) |
| Tool calls in model response | `tool_calls` array, `arguments` as JSON string |
| Tool results sent back | `role: "tool"`, `tool_call_id`, `content` as string |
| `finish_reason` on tool call | `"tool_calls"` |

Verified working with LMStudio + Qwen3.5-35B-A3B via direct API test (March 2026).

---

## `requires_tool_use` Behavior Rule

A role-level guardrail that rejects a final answer on iteration 1 if zero tools were
called, injecting a forcing message to make the model act before concluding.

Enable in a role JSON:
```json
{
  "behavior_rules": {
    "requires_tool_use": true
  }
}
```

**When to use:** Roles given complex multi-step goals with a weak model that tends to
write plans in final-answer format without executing them (observed with
Qwen3.5-35B-A3B on free tier for broad, ambiguous goals).

**When not needed:** Simple, concrete goals (e.g. "run `ls /tmp` and report the output")
cause the model to call tools naturally without forcing.

---

## Debugging Checklist

When an agentic task completes without calling tools:

1. Check `iteration_log` in the task result — look for `status: "final"` on iteration 1
2. If `tool_calls_made: 0`, the model wrote a plan as a final answer
3. Read the raw `response_text` — does it contain `<think>` blocks? (template leak)
4. Test tool calling directly against LMStudio:
   ```python
   payload = {"model": "...", "messages": [...], "tools": [...], "tool_choice": "auto"}
   # check: finish_reason == "tool_calls" and tool_calls array is populated
   ```
5. If direct API test works, the issue is in goal phrasing or behavior rules, not the API
6. If direct API test returns `finish_reason: "stop"` with no `tool_calls`, the model
   doesn't recognise the tool schema — check tool name/parameter format

---

*Last updated: 2026-03-24 — v1.2.6 debug session*
