# MCP Tool Description Best Practices

Guide for anyone adding or editing tools in `app/mcp/core/tools.py`.

---

## The Two Audiences

Every MCP tool has two audiences with different needs:

| Audience | Reads | Needs |
|---|---|---|
| **User / Claude Code** | `description` + `inputSchema` | What does this do? When do I call it? What params? |
| **Internal agents** | `capability_catalog.json` + `capability_registry.py` | What tool name to call? What args? What does it return? |

This guide covers the MCP layer (Fold 1). For agent-facing descriptions see `docs/guides/CAPABILITY_CATALOG_BEST_PRACTICES.md`.

---

## Hub Tool Pattern

MoJoAssistant exposes **14 hub tools** instead of 80+ individual tools. Each hub dispatches on an `action` parameter. This keeps the MCP surface clean while hiding internal complexity.

**Rule: Every hub must have:**
1. A one-line summary (first sentence — shown in tool picker)
2. `Call with no action for help menu.` if the tool returns a help block when called bare
3. A grouped action list with inline param signatures
4. A `required: []` schema (all params optional at schema level; validation happens in code)

---

## Description Structure

```
<One-line summary. Appears in tool picker. Keep under 100 chars.>

[Call with no action for help menu.]

[── SECTION HEADING (if actions fall into groups) ──]
action='name', param1, param2?   — what it does
action='name2'                   — what it does

[── ANOTHER SECTION ──]
...

[Notes on key behaviours, gotchas, output locations]
```

### One-line summary rules
- State what the tool **does**, not what it **is**
- No "IMPORTANT:", "NOTE:", imperative commands to the AI, or robot-speak
- Bad:  `"PRESERVE CONVERSATION CONTEXT: Add this Q&A exchange to memory so I remember..."`
- Good: `"Append a Q&A exchange to conversation memory for cross-session recall."`

### Action list rules
- Format: `action='name', required_param, optional_param?  — short description`
- Group related actions under `── HEADING ──` separators
- Show param names inline — don't make the caller dig into inputSchema to find required params
- Trailing `?` marks optional params; no `?` means required

---

## inputSchema Best Practices

### Every parameter must have a `description`

```python
# Bad
"resource_id": {"type": "string"}

# Good
"resource_id": {"type": "string", "description": "Resource ID to operate on (resource_* actions)."}
```

### Use `enum` whenever the valid values are fixed

```python
# Bad
"tier": {"type": "string", "description": "Resource tier."}

# Good
"tier": {"type": "string", "enum": ["free", "free_api", "paid"], "description": "Billing tier."}
```

### Document defaults explicitly

```python
"limit": {
    "type": "integer",
    "description": "Max results to return (default: 10).",
    "default": 10
}
```

### Keep `required` accurate

- `required: []` is fine for hub tools where the action itself is optional (bare call returns help)
- For standalone tools (`reply_to_task`, `task_session_read`), list genuinely required params

### Add every accepted parameter — even optional ones

If the implementation accepts a param, put it in the schema. Missing params (like `api_key` on `config`) mean callers can't discover or use them without reading source code.

---

## Full vs Lean Description

Some models have tight context limits. Design descriptions to work at two lengths:

**Full** (default): everything above — one-liner + action list + notes + schema descriptions

**Lean** (for constrained contexts): first sentence only + minimal schema. The bare `action` call returns a help block, so the model can self-discover.

Implementation pattern — put the lean summary first so it degrades gracefully:
```python
"description": (
    "Schedule and manage tasks.\n\n"          # ← lean: stop here
    "── DISPATCHING A ROLE TASK ──\n"         # ← full: everything below
    ...
)
```

---

## Anti-patterns to Avoid

| Anti-pattern | Problem | Fix |
|---|---|---|
| Prompt injection in description | Confuses user vs system text; breaks tool pickers | Write neutral descriptions |
| Undocumented params in inputSchema | Callers can't use them without reading source | Add every accepted param |
| Actions without param signatures | Caller must guess required args | Add inline `param, param?` |
| Missing enum on fixed-value params | Callers may pass invalid values | Use `"enum": [...]` |
| Retired tools with live dispatch entries | Dead code + confusion | Remove from `placeholder_tools` set and dispatch |
| Single monolithic description for mixed-purpose tools | Hard to scan | Use `── HEADING ──` section breaks |

---

## Checklist for New Tools

- [ ] One-line summary under 100 chars, neutral tone
- [ ] `Call with no action for help menu.` if bare call returns help
- [ ] All actions listed with inline param signatures
- [ ] Every inputSchema property has a `description`
- [ ] Fixed-value params use `enum`
- [ ] Defaults documented in `description` and `default` field
- [ ] `required` array is accurate
- [ ] `api_key` / `api_key_env` both listed if the tool manages credentials
- [ ] Tested: bare call returns help block; each action returns meaningful errors on bad input

---

## Reference: Current Hub Tool Inventory

| Tool | Purpose | Key Actions |
|---|---|---|
| `get_context` | Orientation + event log + attention inbox | orientation, attention, events, task_session |
| `search_memory` | Semantic search across memory tiers | (single action, parameterized) |
| `add_conversation` | Append Q&A to conversation memory | (single action) |
| `memory` | Memory management | end_conversation, list/remove conversations, add/list/remove documents, stats |
| `knowledge` | Git repo knowledge base | list_repos, add_repo, get_file |
| `config` | Config + resource pool + capabilities + doctor | get/set/list/delete, resource_*, capability_*, doctor* |
| `scheduler` | Task scheduling + daemon control | add, list, get, remove, cleanup, purge, status, daemon_* |
| `dream` | Memory consolidation pipeline | process, list, get, upgrade |
| `agent` | External agent process lifecycle | list_types, start, stop, status, list, restart, destroy, action |
| `external_agent` | HITL bridge + Google Workspace + coding backends | ask_user, check_reply, run_task, google, backend_* |
| `role` | Role library management + Nine Chapter design | list, get, create, edit, design_start, design_answer |
| `task_session_read` | Read full task iteration log | (single action) |
| `task_report_read` | Read normalised task completion record | (single action) |
| `reply_to_task` | Unblock a task waiting for user input | (single action) |
