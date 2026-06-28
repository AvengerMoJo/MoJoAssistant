# Rec 2 — MemoryAction Enum + Typed KnowledgeUnit Mutations

**Source:** autoresearch/EvolveMem integration report (`autoresearch_integration_report.md`)  
**Priority:** HIGH impact / MEDIUM-HIGH effort  
**Implementing agent:** assign to Popo or Rebecca  

---

## Goal

Replace ad-hoc consolidation logic in `HybridMemoryService` with typed, structured memory operations.

EvolveMem's key architectural insight: **memory mutations as a structured action space** — INSERT, UPDATE, MERGE, RETIRE — each with explicit preconditions and postconditions that a reasoning agent can plan against.

This enables safe autonomous memory modification: agents propose `MemoryAction` objects; the service validates and executes them; history is preserved in each knowledge unit.

---

## New File to Create

**`app/memory/memory_action.py`**

### Enum: `MemoryActionType`

```python
from enum import Enum

class MemoryActionType(Enum):
    INSERT_UNIT   = "insert_unit"    # add a new fact/knowledge unit
    UPDATE_FACTS  = "update_facts"   # revise content of an existing unit
    MERGE_UNITS   = "merge_units"    # combine two units into one
    RETIRE_STALE  = "retire_stale"   # mark a unit inactive (soft-delete)
```

### Dataclass: `MemoryAction`

```python
@dataclass
class MemoryAction:
    action_type: MemoryActionType
    target_ids: List[str]          # unit ID(s) this action operates on
    content: Optional[str] = None  # new content for INSERT or UPDATE
    metadata: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""               # why this action was proposed
    proposed_by: str = ""          # role_id of the proposing agent
    timestamp: str = ""            # ISO 8601, set automatically if empty

    def __post_init__(self):
        if not self.timestamp:
            from datetime import datetime, timezone
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryAction": ...
```

### Validation rules (raise `ValueError` if violated)

| Action | target_ids | content required |
|--------|-----------|-----------------|
| INSERT_UNIT | empty or new ID | yes |
| UPDATE_FACTS | exactly 1 existing ID | yes |
| MERGE_UNITS | exactly 2 existing IDs | optional (merged text auto-generated) |
| RETIRE_STALE | 1+ existing IDs | no |

---

## Files to Modify

### 1. `app/services/hybrid_memory_service.py`

Add `execute_action()` and `execute_actions()` methods:

```python
def execute_action(self, action: MemoryAction, role_id: str) -> Dict[str, Any]:
    """
    Execute a single typed MemoryAction. Returns result dict with
    {"success": bool, "action_type": str, "affected_ids": List[str], "error": str}.
    """
    from app.memory.memory_action import MemoryActionType, MemoryAction
    t = action.action_type

    if t == MemoryActionType.INSERT_UNIT:
        self.add_to_knowledge_base(action.content, metadata={
            **action.metadata,
            "proposed_by": action.proposed_by,
            "action_reason": action.reason,
        })
        return {"success": True, "action_type": t.value, "affected_ids": []}

    elif t == MemoryActionType.UPDATE_FACTS:
        # soft update: retire old unit + insert revised version
        self._retire_unit(action.target_ids[0], role_id)
        self.add_to_knowledge_base(action.content, metadata={
            **action.metadata,
            "replaces": action.target_ids[0],
            "proposed_by": action.proposed_by,
        })
        return {"success": True, "action_type": t.value, "affected_ids": action.target_ids}

    elif t == MemoryActionType.MERGE_UNITS:
        merged_text = action.content or self._merge_unit_texts(action.target_ids, role_id)
        for uid in action.target_ids:
            self._retire_unit(uid, role_id)
        self.add_to_knowledge_base(merged_text, metadata={
            **action.metadata,
            "merged_from": action.target_ids,
            "proposed_by": action.proposed_by,
        })
        return {"success": True, "action_type": t.value, "affected_ids": action.target_ids}

    elif t == MemoryActionType.RETIRE_STALE:
        for uid in action.target_ids:
            self._retire_unit(uid, role_id)
        return {"success": True, "action_type": t.value, "affected_ids": action.target_ids}

    return {"success": False, "error": f"Unknown action type: {t}"}

def execute_actions(
    self, actions: List[MemoryAction], role_id: str
) -> List[Dict[str, Any]]:
    """Execute a list of MemoryActions in order. Stops on first failure."""
    results = []
    for action in actions:
        result = self.execute_action(action, role_id)
        results.append(result)
        if not result.get("success"):
            break
    return results
```

Private helper `_retire_unit(unit_id, role_id)`:
- Look up the unit in `pipeline.storage` via `storage.read_json(unit_id)`
- Set `{"retired": True, "retired_at": ISO timestamp}` and `storage.write_json(unit_id, updated)`
- If unit not found, log warning and return (don't raise)

### 2. Knowledge unit storage format (extend, don't break)

When `add_to_knowledge_base()` creates a new unit, the metadata dict should include:
```json
{
  "action_history": [],
  "confidence_score": 1.0,
  "last_validated": "<ISO timestamp>"
}
```

These fields are optional — existing units without them work unchanged.  
Update `add_to_knowledge_base()` in `app/services/hybrid_memory_service.py` to inject defaults.

---

## Exact Import Paths (confirmed from codebase audit)

| Symbol | Module |
|--------|--------|
| `HybridMemoryService` (app layer) | `app.services.hybrid_memory_service` |
| `add_to_knowledge_base()` | inherited from `mojo_memory.services.hybrid_memory_service` line 228 |
| `LocalFileStorageBackend.read_json / write_json` | `mojo_memory.storage.local_fs_backend` |

Knowledge unit IDs: the submodule uses UUIDs generated at insert time and stored in metadata.  
Read the actual storage key format from `mojo_memory/services/memory_service.py` before implementing `_retire_unit`.

---

## Success Criteria

1. `MemoryAction(INSERT_UNIT, content="fact")` → unit appears in next `get_context_for_query()` result
2. `MemoryAction(UPDATE_FACTS, target_ids=["id1"], content="revised")` → old unit marked retired, new unit appears in search
3. `MemoryAction(MERGE_UNITS, target_ids=["id1","id2"])` → both retired, merged unit searchable
4. `MemoryAction(RETIRE_STALE, target_ids=["id1"])` → unit no longer in search results
5. `execute_actions([...])` stops and returns partial results on first failure
6. Existing knowledge units without `action_history` / `confidence_score` fields still load and search correctly

---

## What NOT to do

- Do not modify the submodule's storage schema. All new fields go in metadata, which the submodule stores as an opaque dict.
- Do not make `execute_action` async — the submodule's `add_to_knowledge_base` is synchronous.
- Do not expose `MemoryAction` as an MCP tool yet — this is a library layer. An agent tool that calls it can come later.
