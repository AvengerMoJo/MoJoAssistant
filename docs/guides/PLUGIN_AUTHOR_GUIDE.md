# Plugin Author Guide

How to create custom Memory or Dream providers for MoJoAssistant.

## Overview

MoJoAssistant uses a provider architecture for memory and dream modules. The core app depends only on provider contracts (interfaces), and concrete implementations are pluggable.

```
app/core/                    →  Provider contracts (ABCs)
    ↓
provider_registry/           →  Dynamic provider loading
    ↓
mojo_memory/ (default)       →  Memory provider implementation
dreaming/ (default)          →  Dream provider implementation
```

## Provider Contracts

### MemoryProvider

A memory provider manages conversation memory, knowledge units, and archival.

```python
from app.services.provider_contracts import MemoryProvider, ProviderVersion

class MyMemoryProvider(MemoryProvider):
    def get_version(self) -> ProviderVersion:
        return ProviderVersion(
            provider_name="my_memory",
            provider_version="1.0.0",
            contract_version="1.0",
        )
    
    def add_conversation(self, role_id: str, content: str, metadata=None) -> str:
        # Store conversation, return ID
        ...
    
    def get_conversation(self, role_id: str, conversation_id: str) -> dict | None:
        # Retrieve conversation by ID
        ...
    
    def search_conversations(self, role_id: str, query: str, max_items=10) -> list[dict]:
        # Semantic search over conversations
        ...
    
    def add_knowledge(self, role_id: str, content: str, metadata=None) -> str:
        # Add knowledge unit, return ID
        ...
    
    def search_knowledge(self, role_id: str, query: str, max_items=10) -> list[dict]:
        # Semantic search over knowledge units
        ...
    
    def archive_knowledge(self, role_id: str, knowledge_units: list[dict]) -> str:
        # Archive knowledge units, return archive ID
        ...
    
    def health_check(self) -> dict:
        return {"status": "ok", "details": {...}}
```

### DreamProvider

A dream provider runs the ABCD memory consolidation pipeline.

```python
from app.services.provider_contracts import (
    DreamProvider, ProviderVersion, DreamStageResult, DreamArtifact
)

class MyDreamProvider(DreamProvider):
    def get_version(self) -> ProviderVersion:
        return ProviderVersion(
            provider_name="my_dream",
            provider_version="1.0.0",
            contract_version="1.0",
        )
    
    def run_stage_a(self, conversation_text: str, session_id: str) -> DreamStageResult:
        # Stage A: Ingest raw conversation
        ...
    
    def run_stage_b(self, stage_a_result: DreamStageResult, session_id: str) -> DreamStageResult:
        # Stage B: Semantic chunking
        ...
    
    def run_stage_c(self, stage_b_result: DreamStageResult, session_id: str) -> DreamStageResult:
        # Stage C: Synthesis/clustering
        ...
    
    def run_stage_d(self, stage_c_result: DreamStageResult, stage_b_result=None, session_id="") -> DreamStageResult:
        # Stage D: Archival
        ...
    
    def run_pipeline(self, conversation_text: str, session_id: str, stages=None) -> dict:
        # Run full or partial pipeline
        ...
    
    def validate_input(self, conversation_text: str) -> dict:
        return {"valid": True, "errors": [], "warnings": []}
```

## Registering Your Provider

### Option 1: Environment Variable

Set the provider name (not class path):

```bash
export MOJO_MEMORY_PROVIDER=my_memory
```

Or for dream:

```bash
export MOJO_DREAM_PROVIDER=my_dream
```

Then register your provider class at startup:

```python
from app.services.provider_contracts import get_registry
from my_package.providers.memory import MyMemoryProvider

registry = get_registry()
registry.register_memory_provider("my_memory", MyMemoryProvider)
```

### Option 2: Programmatic Registration

```python
from app.services.provider_contracts import get_registry

registry = get_registry()
registry.register_memory_provider("my_memory", MyMemoryProvider)
registry.register_dream_provider("my_dream", MyDreamProvider)
```

### Option 3: Auto-Discovery (Plugin Package)

Create a package that registers on import:

```python
# my_package/providers/__init__.py
from app.services.provider_contracts import get_registry
from .memory import MyMemoryProvider
from .dream import MyDreamProvider

registry = get_registry()
registry.register_memory_provider("my_memory", MyMemoryProvider)
registry.register_dream_provider("my_dream", MyDreamProvider)
```

## Testing Your Provider

Run the conformance suite against your implementation:

```bash
pytest tests/conformance/test_provider_conformance.py -v
```

Or create a custom test class:

```python
from tests.conformance.test_provider_conformance import MemoryProviderConformance

class TestMyMemoryProvider(MemoryProviderConformance):
    def create_provider(self):
        return MyMemoryProvider(data_dir="/tmp/test")
```

## Versioning

Providers must report three version strings:

- `provider_name`: Unique identifier (e.g., "my_memory")
- `provider_version`: Your provider's version (semver)
- `contract_version`: The contract version you implement (major.minor)

The app validates `contract_version` at startup and rejects incompatible providers.

## Capabilities

Providers can report capabilities:

```python
def get_capabilities(self) -> dict:
    return {
        "provider_name": "my_memory",
        "supports_embeddings": True,
        "supports_archive": True,
        "custom_feature": True,
    }
```

## Migration from Legacy Imports

If you have code using:

```python
# OLD (legacy)
from app.memory import MemoryManager
from app.services.memory_service import MemoryService
```

Replace with:

```python
# NEW (provider-based)
from app.services.memory_backend import get_memory_provider

provider = get_memory_provider()
provider.add_conversation(role_id, content)
```

Or for backward compatibility:

```python
# Still works (shim)
from app.services.memory_service import MemoryService
```
