# Provider Compatibility Matrix

Version compatibility between MoJoAssistant core and memory/dream providers.

## Contract Versions

| Contract | Current Version | Status |
|----------|----------------|--------|
| MemoryProvider | 1.0 | Active |
| DreamProvider | 1.0 | Active |

## Default Providers

| Provider | Package | Version | Contract | Status |
|----------|---------|---------|----------|--------|
| mojo_memory | dreaming-memory-pipeline | 1.0.0 | MemoryProvider 1.0 | Active |
| mojo_dream | dreaming-memory-pipeline | 1.0.0 | DreamProvider 1.0 | Active |

## Compatibility Rules

1. **Major version mismatch**: Provider will be rejected at startup
2. **Minor version mismatch**: Warning logged, provider may work
3. **Patch version mismatch**: No check, always compatible

## Version Format

```
provider_version: MAJOR.MINOR.PATCH
contract_version: MAJOR.MINOR
```

Examples:
- Provider `1.0.0` with contract `1.0` → compatible
- Provider `2.0.0` with contract `1.0` → **rejected** (major mismatch)
- Provider `1.1.0` with contract `1.0` → compatible (minor mismatch OK)
- Provider `1.0.1` with contract `1.0` → compatible

## Environment Variables

| Variable | Values | Description |
|----------|--------|-------------|
| `MOJO_MEMORY_PROVIDER` | `mojo_memory`, custom name | Select memory provider |
| `MOJO_DREAM_PROVIDER` | `mojo_dream`, custom name | Select dream provider |
| `MOJO_MEMORY_SERVICE_CLASS` | Dotted class path | Override memory service class |
| `MOJO_HYBRID_MEMORY_SERVICE_CLASS` | Dotted class path | Override hybrid memory service class |

## Provider Lifecycle

```
M1 (Contract Freeze)
  └─ Contracts defined, versioned
  └─ Default providers implement contracts
  └─ Registry loads providers

M2 (Default Provider Compliance)
  └─ mojo_memory passes conformance suite
  └─ mojo_dream passes conformance suite
  └─ App routes through provider interfaces

M3 (Compatibility Sunset)
  └─ Legacy imports deprecated
  └─ Shim usage metric near zero
  └─ Migration guide published

M4 (Full Modular Cutover)
  └─ Legacy shims removed
  └─ Hard CI fail on legacy imports
  └─ Only provider interface used
```

## Third-Party Providers

Any provider that implements the contract interface can be registered:

```python
from app.services.provider_contracts import get_registry

# Register your custom provider
registry = get_registry()
registry.register_memory_provider("custom_memory", MyCustomMemoryProvider)

# Use it
import os
os.environ["MOJO_MEMORY_PROVIDER"] = "custom_memory"
```

## Testing Compatibility

Run the conformance suite:

```bash
# Test default providers
pytest tests/conformance/ -v

# Test with custom provider
MOJO_MEMORY_PROVIDER=custom_memory pytest tests/conformance/ -v
```

## Breaking Changes

When contract version increments (e.g., 1.0 → 2.0):

1. New required methods may be added
2. Existing method signatures may change
3. Return types may change
4. Providers must update to match new contract

The app will reject providers with mismatched contract versions at startup.
