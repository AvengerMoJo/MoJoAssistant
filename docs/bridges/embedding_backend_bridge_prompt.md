# Embedding Backend Bridge Prompt

Use this prompt for an implementation agent to add a third-party embedding backend plugin.

## Goal
Implement a new embedding backend that conforms to `mojo_memory.embeddings.backends.base.EmbeddingBackend` and can be registered through `mojo_memory.embeddings.registry.register_backend`.

## Required Outputs
1. New backend class file under `submodules/dreaming-memory-pipeline/src/mojo_memory/embeddings/backends/`.
2. Registration hook (either explicit registration call or documented bootstrap path).
3. Conformance tests extending `tests/conformance/test_embedding_backend_conformance.py`.
4. Minimal runtime config example for enabling the backend.

## Contract Requirements
- Implement:
  - `get_text_embedding(text, prompt_name="passage") -> List[float]`
  - `get_batch_embeddings(texts) -> List[List[float]]`
  - `get_info() -> Dict[str, Any]`
  - `change_model(model_name) -> bool`
- Must return deterministic shape and stable dimension per model.
- Must degrade gracefully (fallback or explicit error) when provider endpoint/model is unavailable.

## Validation Commands
```bash
python3 -m pytest tests/conformance/test_embedding_backend_conformance.py -q
python3 -m pytest tests/smoke/test_imports.py -q
```

## Done Criteria
- Backend selectable by config (`embedding.backend`).
- Conformance tests pass.
- No core changes needed outside the embedding backend contract/registry path.
