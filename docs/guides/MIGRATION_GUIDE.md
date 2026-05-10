# Migration Guide: Legacy Imports to Provider Interface

This guide helps you migrate code from legacy `app.memory` / `app.services` imports to the new provider interface.

## What Changed

### Before (Legacy)
```python
from app.memory import MemoryManager
from app.services.memory_service import MemoryService
from app.services.hybrid_memory_service import HybridMemoryService
```

### After (Provider-based)
```python
from app.services.memory_backend import get_memory_provider, get_dream_provider

# Memory operations
memory = get_memory_provider()
memory.add_conversation(role_id, content)
memory.search_knowledge(role_id, query)

# Dream operations
dream = get_dream_provider()
dream.run_pipeline(conversation_text, session_id)
```

## Migration Steps

### Step 1: Find Legacy Imports

Search your codebase:

```bash
grep -r "from app.memory" --include="*.py"
grep -r "from app.services.memory_service" --include="*.py"
grep -r "from app.services.hybrid_memory_service" --include="*.py"
```

### Step 2: Replace Imports

| Legacy Import | New Import |
|---------------|------------|
| `from app.memory import MemoryManager` | `from app.services.memory_backend import get_memory_provider` |
| `from app.memory.simplified_embeddings import SimpleEmbedding` | Keep as-is (shim still works) |
| `from app.services.memory_service import MemoryService` | `from app.services.memory_backend import get_memory_provider` |

### Step 3: Update Code Patterns

**Pattern 1: Direct instantiation**
```python
# OLD
service = MemoryService(data_dir="/path")
service.add_conversation(role_id, content)

# NEW
provider = get_memory_provider(data_dir="/path")
provider.add_conversation(role_id, content)
```

**Pattern 2: Global singleton**
```python
# OLD
from app.services.memory_service import MemoryService
_service = MemoryService()

# NEW
from app.services.memory_backend import get_memory_provider
_provider = get_memory_provider()
```

**Pattern 3: HybridMemoryService**
```python
# OLD
from app.services.hybrid_memory_service import HybridMemoryService
hybrid = HybridMemoryService()

# NEW
from app.services.memory_backend import get_memory_provider
provider = get_memory_provider()  # Returns HybridMemoryService by default
```

## Backward Compatibility

Legacy imports still work via compatibility shims. Your code will continue to function, but you should migrate for:

1. **Future-proofing**: Shims will be removed in M4 milestone
2. **Provider flexibility**: New interface allows swapping providers
3. **Cleaner imports**: No more `sys.path` manipulation

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `MOJO_MEMORY_PROVIDER` | Select memory provider by name | `mojo_memory` |
| `MOJO_DREAM_PROVIDER` | Select dream provider by name | `mojo_dream` |
| `MOJO_MEMORY_SERVICE_CLASS` | Override memory service class path | `mojo_memory.services.memory_service.MemoryService` |
| `MOJO_HYBRID_MEMORY_SERVICE_CLASS` | Override hybrid memory service class path | `mojo_memory.services.hybrid_memory_service.HybridMemoryService` |

## Troubleshooting

### "Module not found" errors

Ensure the submodule is initialized:
```bash
git submodule update --init --recursive
```

Or install the package:
```bash
pip install submodules/dreaming-memory-pipeline/
```

### "Provider not registered" errors

Check that the provider is importable:
```python
from app.services.provider_contracts import get_registry
registry = get_registry()
print(registry._memory_providers)
```

### Contract version mismatch

Ensure your provider's `contract_version` matches the app's expected version:
```python
provider = get_memory_provider()
version = provider.get_version()
print(f"Contract version: {version.contract_version}")
```

## Timeline

- **M1 (Current)**: Legacy imports work via shims
- **M2**: Legacy imports deprecated with warnings
- **M3**: Legacy imports removed, hard CI fail
- **M4**: Shims removed entirely
