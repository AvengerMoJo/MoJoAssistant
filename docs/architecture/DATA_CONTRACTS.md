# MoJo Data Contracts

Status: v1.0 — Stable  
Date: 2026-05-10

These schemas define the API boundary between MoJo Core and pluggable modules.  
Any module that reads or writes these stores must conform to the schemas below.  
Schema versions increment when fields are added or removed from the required set.

---

## ConversationStore@1.0

**Path:** `$MEMORY_PATH/conversations_multi_model.json`  
**Owner:** MoJo Core (memory_service writes; Memory modules read)  
**Purpose:** Raw persistent conversation history across all roles.

```json
{
  "conversations": [
    {
      "id": "string — uuid",
      "role_id": "string — role identifier, null for user-level",
      "title": "string",
      "timestamp": "ISO-8601",
      "messages": [
        {
          "role": "user | assistant | system | tool",
          "content": "string",
          "timestamp": "ISO-8601",
          "model": "string | null"
        }
      ],
      "metadata": {
        "source": "string — mcp | scheduler | role_chat | import",
        "session_id": "string | null",
        "tags": ["string"]
      }
    }
  ]
}
```

**Stability guarantees:**
- `id`, `role_id`, `timestamp`, `messages[].role`, `messages[].content` — frozen; never removed
- `metadata` — extensible; modules must tolerate unknown keys
- `messages[].model` — optional; may be null for older records

---

## TaskSession@1.0

**Path:** `$MEMORY_PATH/task_sessions/{task_id}.json`  
**Owner:** MoJo Core (scheduler writes; Memory modules, Growth modules read)  
**Purpose:** Full message transcript for one agentic task execution.

```json
{
  "task_id": "string",
  "role_id": "string",
  "goal": "string",
  "status": "pending | running | completed | failed | waiting_for_input",
  "created_at": "ISO-8601",
  "completed_at": "ISO-8601 | null",
  "messages": [
    {
      "role": "user | assistant | tool",
      "iteration": "integer",
      "tool_name": "string | null",
      "content": "string",
      "timestamp": "ISO-8601 | null"
    }
  ],
  "final_answer": "string | null",
  "metrics": {
    "iterations": "integer",
    "duration_seconds": "float",
    "resource_id": "string | null",
    "model": "string | null"
  }
}
```

**Stability guarantees:**
- `task_id`, `role_id`, `goal`, `status`, `messages` — frozen
- `metrics` — extensible; modules must tolerate unknown fields
- `final_answer` — present when status is `completed`; null otherwise

---

## RoleDefinition@1.0

**Path:** `$MEMORY_PATH/roles/{role_id}.json`  
**Owner:** MoJo Core (role system writes; all modules read)  
**Purpose:** Role identity, capabilities, personality, and policy.

```json
{
  "id": "string",
  "name": "string",
  "archetype": "string",
  "agent_type": "assistant | scheduler | orchestrator",
  "persona": "string — free text description",
  "capabilities": ["string — capability category names"],
  "nine_chapter_score": "integer 0–100 | null",
  "nine_chapter_dimensions": {
    "core_values": "integer 0–100",
    "emotional_reaction": "integer 0–100",
    "cognitive_style": "integer 0–100",
    "social_orientation": "integer 0–100",
    "adaptability": "integer 0–100"
  },
  "local_only": "boolean",
  "schedule_cron": "string | null",
  "max_iterations": "integer",
  "policy": {
    "danger_budget": "integer",
    "denied_tools": ["string"],
    "checkers": ["string"]
  },
  "behavior_rules": ["string"],
  "system_prompt_override": "string | null"
}
```

**Stability guarantees:**
- `id`, `name`, `capabilities`, `local_only` — frozen
- `nine_chapter_dimensions` — optional block; modules must not require it
- `policy` — extensible; unknown checker names are silently ignored by old core versions

---

## DreamArchive@1.0

**Path:** `$MEMORY_PATH/dreams/{role_id}/` or `$MEMORY_PATH/roles/{role_id}/dreams/`  
**Owner:** Memory modules (write); MoJo Core search reads via module interface  
**Purpose:** Consolidated semantic memory produced by the memory module's consolidation pipeline.

```
dreams/
  {role_id}/
    {YYYY-MM-DD}/
      archive.json        ← D-tier consolidated archive
      chunks.json         ← B-tier fact chunks
      clusters.json       ← C-tier thematic clusters
      metadata.json       ← pipeline run metadata
```

**`archive.json` schema:**
```json
{
  "role_id": "string",
  "date": "YYYY-MM-DD",
  "pipeline_version": "string",
  "units": [
    {
      "id": "string",
      "content": "string — distilled fact or insight",
      "source_session_ids": ["string"],
      "tags": ["string"],
      "embedding": [0.0]
    }
  ]
}
```

**Stability guarantees:**
- `role_id`, `date`, `units[].content` — frozen
- `units[].embedding` — optional; absent if embedding model not configured
- `pipeline_version` — used by future modules to know which pipeline produced the archive

---

## DynamicTool@1.0

**Path:** `$MEMORY_PATH/config/dynamic_tools.json`  
**Owner:** Skill modules and agents (write); Executor, CapabilityResolver (read)  
**Purpose:** Runtime-registered tools beyond the built-in capability catalog.

```json
{
  "last_updated": "ISO-8601",
  "tools": [
    {
      "name": "string — unique tool name",
      "description": "string",
      "category": "string — capability category",
      "danger_level": "low | medium | high | critical",
      "executor": "bash | python | http",
      "command": "string — template with {arg_name} placeholders",
      "args": {
        "arg_name": {
          "type": "string | integer | boolean",
          "description": "string",
          "required": "boolean",
          "default": "any | null"
        }
      },
      "install_hint": "string | null",
      "preconditions": ["string — binary:name, network:egress, etc."],
      "health_check": "string | null"
    }
  ]
}
```

**Stability guarantees:**
- `name`, `description`, `executor`, `command` — frozen
- `preconditions`, `health_check` — optional; used by capability pre-flight when present
- `danger_level` — defaults to `medium` if absent

---

## NineChapterScore@1.0

**Produced by:** Persona modules  
**Consumed by:** Role system, Growth modules, BRIDLE framework  
**Embedded in:** `RoleDefinition@1.0` under `nine_chapter_dimensions`

Five dimensions, each 0–100. Values are **predictive confidence** — how reliably this role will exhibit the trait — not a quality grade. 50 is a calibrated neutral, not a mediocre score.

| Dimension | What it predicts |
|-----------|-----------------|
| `core_values` | Consistency of ethical and value-based decisions |
| `emotional_reaction` | Predictability of emotional tone and empathy responses |
| `cognitive_style` | Analytical vs. intuitive reasoning preference |
| `social_orientation` | Collaborative vs. independent working tendency |
| `adaptability` | Flexibility when goals shift or constraints change |

`nine_chapter_score` (the top-level field) is a weighted overall. Default weight: equal across all five dimensions. Growth modules may recalibrate weights based on observed task history.

---

## Schema Versioning Rules

1. **Minor additions** (new optional fields) do not increment the version. All modules must tolerate unknown fields.
2. **Field removal or type change** increments the version (e.g. `ConversationStore@2.0`). MoJo Core will reject modules declaring an incompatible version.
3. **New required fields** also increment the version.
4. Modules declare compatibility in their `module.json` under `data_contracts`.

---

## Adding a New Data Contract

If a module needs a new store that other modules may also consume:

1. Define the schema here with a `@1.0` version tag.
2. Document path, owner, and consumers.
3. Add to the module's `module.json` under `data_contracts`.
4. MoJo Core does not need to change — only the modules that read/write the new store.
