# Classification System — Type Fields & i18n Safety

## The Problem

MoJoAssistant uses string-based classification fields throughout its config and
runtime: `agent_type`, `archetype`, `danger_level`, `event_type`, `task_type`,
`hitl_level`, and others. Any code that matches these by string is implicitly
English-only — keyword parsing, display filtering, and policy rules all break
if a user writes values in another language.

## The Rule

**Canonical identifiers are always language-neutral slugs.
Display labels are always separate.**

A canonical ID:
- Is lowercase ASCII with underscores (`researcher`, `task_failed`, `high`)
- Is used in all code logic, config matching, policy rules, and JSON schemas
- Never changes meaning based on locale
- Is defined once in a registry (see below)

A display label:
- Is human-readable text shown in UI, dashboards, and wizard prompts
- May be translated or customised per locale
- Is never used in code logic or string matching

## Where This Applies

| Field | Canonical ID examples | Used in |
|---|---|---|
| `agent_type` | `researcher`, `coder`, `reviewer`, `ops`, `analyst`, `assistant` | dashboard filter, role config |
| `archetype` | `empathetic_connector`, `analytical_pragmatist` | role display, ConfigDoctor |
| `danger_level` | `low`, `medium`, `high` | tool_catalog, policy engine |
| `event_type` | `task_failed`, `task_completed`, `task_waiting_for_input` | EventLog, attention routing |
| `task_type` | `dreaming`, `assistant`, `agent`, `scheduled` | attention routing, scheduler |
| `hitl_level` | `0`–`5` (numeric) | attention classifier |
| `tool_access` | `file`, `exec`, `memory`, `web`, `comms`, `terminal`, `orchestration` | tool_catalog, role policy |

## Rules for New Classification Fields

1. **Define the canonical ID set first** — before writing any code, list the
   allowed values in a registry file or inline constant.

2. **Store and match canonical IDs only** — JSON config, database rows, and
   all code comparisons use only the slug.

3. **Never keyword-match free text to derive a canonical ID** — if user input
   must map to a canonical type, present explicit choices. Accept verbatim
   storage for unknown values rather than guessing.

4. **Keep display labels out of logic** — if the dashboard shows "Researcher"
   for `agent_type: researcher`, that mapping lives in the display layer only.

5. **Unknown values are valid** — a value not in the known set is stored as-is
   (verbatim, whitespace → underscores). The system treats it as a custom type.
   No validation error. The UI shows it as-is.

## User Input for Classification (Wizard / Forms)

When asking a user to classify something, present explicit choices. Custom
input is stored separately — never let free text silently become `agent_type`.

```
# Good — explicit choices, custom path with separate label field
User picks "researcher" → agent_type: "researcher"  (no label needed)
User types "研究員"      → agent_type: "custom", agent_type_label: "研究員"
User types "My Lead"    → agent_type: "custom", agent_type_label: "My Lead"

# Bad — free text becomes canonical ID directly
User types "coding expert" → agent_type: "coding_expert"  ← brittle, untranslatable
```

The `role_designer.py` `_infer_agent_type()` returns a `(agent_type, label)`
tuple. Known types match case-insensitively and return `(type, None)`. Anything
else returns `("custom", original_text)`. The spec writer adds `agent_type_label`
only when label is not None.

### LLM Role in Classification

LLM can suggest a likely built-in type or a slug for a custom type, but it
never writes `agent_type` directly. User confirmation (picking from the list)
is the only write path to `agent_type`.

## Display Label Registry (Future)

When the UI needs localised labels, add a display registry alongside the
canonical set — do not embed labels in the canonical ID:

```json
{
  "agent_type": {
    "researcher": { "en": "Researcher", "zh-TW": "研究員", "zh-HK": "研究員" },
    "coder":      { "en": "Coder",      "zh-TW": "工程師", "zh-HK": "程式員" },
    "reviewer":   { "en": "Reviewer",   "zh-TW": "審查員", "zh-HK": "審閱員" },
    "ops":        { "en": "Ops",        "zh-TW": "維運",   "zh-HK": "維運"   },
    "analyst":    { "en": "Analyst",    "zh-TW": "分析師", "zh-HK": "分析師" },
    "assistant":  { "en": "Assistant",  "zh-TW": "助理",   "zh-HK": "助理"   }
  }
}
```

This registry does not exist yet — the dashboard currently renders canonical
IDs directly. Add it when first localisation is needed.

## Current Compliance Status

| Field | Compliant | Notes |
|---|---|---|
| `agent_type` | ✅ | Explicit choices in wizard; verbatim fallback |
| `archetype` | ✅ | Inferred from numeric scores, never from text |
| `danger_level` | ✅ | Defined in tool_catalog.json, matched exactly |
| `event_type` | ✅ | Defined as constants in EventLog |
| `task_type` | ✅ | Defined in scheduler config |
| `hitl_level` | ✅ | Numeric |
| `tool_access` | ✅ | Defined in tool_catalog.json categories |
| Role `purpose` / `system_prompt` | N/A | Free text, never matched by code |
| Role `name` / `id` | ✅ | `id` is always ASCII slug; `name` is display-only |
