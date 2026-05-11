# Module Adoption How-To

## Purpose
This guide shows how to add and adopt a pluggable module in MoJoAssistant, with a concrete example for a custom memory provider.

## Current Reference Implementation
Use these as the baseline reference:

- Memory provider adapter:
  - `submodules/dreaming-memory-pipeline/src/mojo_memory/services/memory_provider.py`
- Memory provider contract:
  - `app/services/provider_contracts.py` (`MemoryProvider`)
- Default memory module descriptor:
  - `submodules/dreaming-memory-pipeline/module.json`

## What a Memory Module Must Implement
A memory provider must subclass `MemoryProvider` and implement:

1. `get_version()`
2. `add_conversation(role_id, content, metadata=None)`
3. `get_conversation(role_id, conversation_id)`
4. `search_conversations(role_id, query, max_items=10)`
5. `add_knowledge(role_id, content, metadata=None)`
6. `search_knowledge(role_id, query, max_items=10)`
7. `archive_knowledge(role_id, knowledge_units)`
8. `health_check()`

Optional but recommended:
- `get_capabilities()`

## Persona Module Interface (PersonaModule@1.0)

Persona providers use the `PersonaProvider` contract in `app/services/provider_contracts.py`
and must implement:

1. `get_version()`
2. `generate(spec)` -> role definition dict
3. `score(role_def)` -> persona score object
4. `list_personas(filter=None)` -> persona catalog entries

Reference implementation:
- `app/roles/persona_provider.py` (`AgencyPersonaModule`)
- `submodules/agency-agents/module.json`

## Example: Add a Custom Memory Provider

### 1. Create provider class

Create `my_memory/provider.py`:

```python
from app.services.provider_contracts import MemoryProvider, ProviderVersion


class MyMemoryProvider(MemoryProvider):
    def __init__(self, data_dir=None, **kwargs):
        self._data_dir = data_dir

    def get_version(self) -> ProviderVersion:
        return ProviderVersion(
            provider_name="my_memory",
            provider_version="1.0.0",
            contract_version="1.0",
        )

    def add_conversation(self, role_id, content, metadata=None) -> str:
        return "conv_1"

    def get_conversation(self, role_id, conversation_id):
        return {"id": conversation_id, "content": "example"}

    def search_conversations(self, role_id, query, max_items=10):
        return []

    def add_knowledge(self, role_id, content, metadata=None) -> str:
        return "ku_1"

    def search_knowledge(self, role_id, query, max_items=10):
        return []

    def archive_knowledge(self, role_id, knowledge_units):
        return "archive_1"

    def health_check(self):
        return {"status": "ok", "details": {"provider": "my_memory"}}
```

### 2. Add module descriptor

Create `submodules/my-memory-module/module.json`:

```json
{
  "name": "my_memory",
  "version": "1.0.0",
  "contract_version": "1.0",
  "provider_type": "memory",
  "entry_point": "my_memory.provider.MyMemoryProvider",
  "description": "Custom memory provider example",
  "dependencies": [],
  "data_contracts": {
    "ConversationStore": "1.0"
  }
}
```

Notes:
- `provider_type` must be `memory`
- `entry_point` must be a valid dotted import path
- `contract_version` must match core contract major version

### 3. Ensure import path is available

If using submodule layout, keep provider package under `<submodule>/src/...` so discovery can import it.

### 4. Select provider at runtime

Set:

```bash
export MOJO_MEMORY_PROVIDER=my_memory
```

The registry resolves by provider name (not class path).

### 5. Verify module discovery and health

```bash
python3 - <<'PY'
from app.services.provider_contracts import get_registry
r = get_registry()
mods = r.discover_modules()
print([m.get("name") for m in mods])
print(r.get_module_load_errors())
PY
```

Expected:
- module name appears in discovered list
- load errors dict is empty

### 6. Run conformance tests

```bash
python3 -m pytest tests/conformance/test_provider_conformance.py -q
```

## Alternative Registration (Programmatic)

If you do not use `module.json` discovery, register directly:

```python
from app.services.provider_contracts import get_registry
from my_memory.provider import MyMemoryProvider

registry = get_registry()
registry.register_memory_provider("my_memory", MyMemoryProvider)
```

## Troubleshooting

1. `Memory provider 'X' not registered`
- Check `MOJO_MEMORY_PROVIDER`
- Run module discovery and inspect `get_module_load_errors()`

2. `No module named ...`
- Ensure provider package is importable (usually under submodule `src/`)

3. Conformance failures
- Verify your class subclasses `MemoryProvider`
- Match required method signatures and return shapes

4. MCP memory search returns degraded/empty responses
- If provider/plugin is missing or fails to load, MCP returns:
  - `status: "degraded"`
  - message: memory provider not configured/failed
- If provider loads but no data exists yet, MCP returns:
  - `status: "ok"`
  - `total: 0`
  - message: `"Your memory model is empty. Add conversations/documents first."`

This is expected behavior and prevents server crashes when memory plugin loading fails.

## Adoption Checklist

1. Provider class implements full `MemoryProvider` contract
2. `module.json` added and valid
3. Provider discoverable with empty load errors
4. Runtime selection via `MOJO_MEMORY_PROVIDER`
5. Conformance tests pass
6. Ownership/smoke checks pass after integration
