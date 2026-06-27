# Rec 4 — Self-Tunable Parameter Surface for Role Configs

**Source:** autoresearch/EvolveMem integration report (`autoresearch_integration_report.md`)  
**Priority:** MEDIUM impact / LOW effort (~50 lines + validation logic)  
**Implementing agent:** assign to Popo  

---

## Goal

Let agents propose parameter tweaks to their own operating config after a task session completes.  
Inspired by karpathy/autoresearch's scaffold vs. experiment boundary:

- **Immutable scaffold** (`prepare.py`) — role identity, capability list, core policies
- **Mutable experiment surface** (`train.py`) — hyperparameters, tool limits, memory depth

Here:
- **Immutable** — role name, `allowed_tools`, `policy.*`, `behavior_rules.*`
- **Mutable (self-tunable)** — `max_iterations`, `memory_search_depth`, `dispatch_preferences`, and any custom fields the role owner explicitly opts in

---

## Schema Change: Role Config Files

**Location:** `~/.memory/roles/<role_id>/config.json` (or `role.json` — check actual filename per role)

Add an optional `self_tunable_params` section:

```json
{
  "role_id": "popo",
  "name": "Popo",
  ...existing fields...,
  "self_tunable_params": {
    "max_iterations": {
      "current": 40,
      "min": 10,
      "max": 80,
      "description": "Task iteration budget"
    },
    "memory_search_depth": {
      "current": 10,
      "min": 5,
      "max": 30,
      "description": "Number of results returned by memory_search"
    }
  }
}
```

If `self_tunable_params` is absent or empty, the role is fully immutable (default, backward-compatible).

---

## New File to Create

**`app/scheduler/role_self_tuning.py`**

### Function: `propose_param_update()`

```python
def propose_param_update(
    role_id: str,
    param_name: str,
    proposed_value: Any,
    reason: str = "",
) -> Dict[str, Any]:
    """
    Validate and apply a self-tuning proposal from an agent.

    Returns:
        {"success": True, "applied": {param_name: new_value}}
        {"success": False, "error": "<reason>"}

    Rules:
    - param_name must exist in self_tunable_params
    - proposed_value must be within [min, max] for numeric params
    - Write atomically: read → merge → write .tmp → rename
    - Log the change with old/new value and reason
    """
```

### Function: `get_tunable_params()`

```python
def get_tunable_params(role_id: str) -> Dict[str, Any]:
    """
    Return the current self_tunable_params dict for a role.
    Returns {} if the role has no tunable params or doesn't exist.
    """
```

### Function: `reset_tunable_params()`

```python
def reset_tunable_params(role_id: str) -> Dict[str, Any]:
    """
    Reset all tunable params to their 'default' values (if defined).
    Returns dict of {param: reset_value} for each param reset.
    Used for rollback after a failed experiment cycle.
    """
```

---

## Files to Modify

### 1. Role config loader (wherever role configs are read)

Find where `config.json` / `role.json` is read for role dispatch (likely `app/scheduler/agentic_executor.py` or a role loader).

After loading, extract `self_tunable_params` and apply `current` values to task config:

```python
tunable = role_config.get("self_tunable_params", {})
for param, spec in tunable.items():
    if param not in task.config:  # don't override explicit task config
        task.config[param] = spec.get("current", spec.get("default"))
```

### 2. `app/scheduler/agentic_executor.py` — post-task hook

After a successful task completion, give the agent one opportunity to propose a self-tune.

This does NOT happen automatically — only if the task's final answer contains a special marker:

```
SELF_TUNE: max_iterations=50 reason="Task needed more cycles than budgeted"
```

Detection (in the FINAL_ANSWER parsing block):

```python
import re
_SELF_TUNE_RE = re.compile(
    r"SELF_TUNE:\s*(\w+)\s*=\s*(\S+)\s+reason=\"([^\"]+)\"", re.IGNORECASE
)
for m in _SELF_TUNE_RE.finditer(final_answer):
    param, value, reason = m.group(1), m.group(2), m.group(3)
    from app.scheduler.role_self_tuning import propose_param_update
    result = propose_param_update(
        role_id=task.config.get("role_id", ""),
        param_name=param,
        proposed_value=_coerce_value(value),
        reason=reason,
    )
    self._log(f"Self-tune proposal: {param}={value} → {result}")
```

Helper `_coerce_value(s)`: try `int(s)`, then `float(s)`, else return `s` as-is.

### 3. `app/scheduler/capability_registry.py` — document the SELF_TUNE marker

Add a note to the `ask_user` or general execution context description explaining that agents MAY emit `SELF_TUNE:` lines in their FINAL_ANSWER (not as a tool call, just a text marker).

---

## File Paths (confirmed from codebase audit)

| Symbol | Location |
|--------|----------|
| Role configs | `~/.memory/roles/<role_id>/` — check actual filename (config.json or role.json) |
| `agentic_executor.py` FINAL_ANSWER parsing | `app/scheduler/agentic_executor.py` — search for `FINAL_ANSWER` or `final_answer =` |
| `capability_registry.py` | `app/scheduler/capability_registry.py` |

Before implementing, run:
```bash
ls ~/.memory/roles/popo/
```
to confirm the config filename and current structure.

---

## Success Criteria

1. A role config with `self_tunable_params.max_iterations.current=40` causes dispatched tasks to use `max_iterations=40` when not overridden
2. `propose_param_update("popo", "max_iterations", 55, "needed more cycles")` → updates `current` in the JSON file, returns `{"success": True}`
3. `propose_param_update("popo", "max_iterations", 200, ...)` → returns `{"success": False, "error": "200 exceeds max 80"}` — file unchanged
4. `propose_param_update("popo", "allowed_tools", [...], ...)` → returns `{"success": False, "error": "param not in self_tunable_params"}` — immutability enforced
5. A task whose FINAL_ANSWER contains `SELF_TUNE: max_iterations=50 reason="..."` triggers a `propose_param_update()` call
6. Roles without `self_tunable_params` are completely unchanged — zero behavior difference

---

## What NOT to do

- Do not let agents tune security-sensitive fields (`allowed_tools`, `policy.*`, `behavior_rules.*`) — these are always immutable regardless of what `self_tunable_params` says
- Do not apply SELF_TUNE proposals from failed tasks — only `success=True` tasks may propose
- Do not require role owners to add `self_tunable_params` — its absence means fully immutable (safe default)
- Do not make self-tuning retroactive — it only affects future task dispatches, not the current session
