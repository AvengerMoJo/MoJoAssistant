"""Provider-interface runtime helpers for benchmark runners."""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.memory_backend import get_memory_provider


class ProviderMemoryRuntime:
    """Thin benchmark adapter over MemoryProvider contract methods."""

    def __init__(self, provider: Any, role_id: str = "benchmark"):
        self.provider = provider
        self.role_id = role_id

    @classmethod
    def build(
        cls,
        *,
        role_id: str,
        data_dir: str,
        embedding_backend: str,
        embedding_model: str,
        config: Dict[str, Any] | None = None,
    ) -> "ProviderMemoryRuntime":
        provider = get_memory_provider(
            data_dir=data_dir,
            embedding_backend=embedding_backend,
            embedding_model=embedding_model,
            embedding_device="cpu",
            config=config or {},
        )
        return cls(provider=provider, role_id=role_id)

    def add_message(self, role: str, content: str, metadata: Dict[str, Any] | None = None) -> str:
        payload = f"{role}: {content}"
        meta = {"role": role}
        if metadata:
            meta.update(metadata)
        return self.provider.add_conversation(self.role_id, payload, meta)

    def get_context(self, query: str, max_items: int = 15) -> List[Dict[str, Any]]:
        conv = self.provider.search_conversations(self.role_id, query, max_items=max_items)
        know = self.provider.search_knowledge(self.role_id, query, max_items=max_items)
        merged = (conv or []) + (know or [])
        normalized: List[Dict[str, Any]] = []
        for item in merged[:max_items]:
            normalized.append(
                {
                    "source": item.get("source", "memory"),
                    "content": item.get("content", item.get("text", "")),
                    "relevance": float(item.get("score", item.get("relevance", 0.0))),
                }
            )
        return normalized
