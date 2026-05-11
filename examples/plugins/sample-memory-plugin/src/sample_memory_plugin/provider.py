"""Sample in-memory MemoryProvider implementation for Plugin SDK."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.services.provider_contracts import MemoryProvider, ProviderVersion


class PluginProvider(MemoryProvider):
    def __init__(self, **_: Any):
        self._conv: Dict[str, List[Dict[str, Any]]] = {}
        self._ku: Dict[str, List[Dict[str, Any]]] = {}

    def get_version(self) -> ProviderVersion:
        return ProviderVersion("sample_memory_plugin", "0.1.0", "1.0")

    def add_conversation(
        self, role_id: str, content: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        item = {"id": str(uuid4()), "content": content, "metadata": metadata or {}}
        self._conv.setdefault(role_id, []).append(item)
        return item["id"]

    def get_conversation(self, role_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        for item in self._conv.get(role_id, []):
            if item["id"] == conversation_id:
                return item
        return None

    def search_conversations(self, role_id: str, query: str, max_items: int = 10) -> List[Dict[str, Any]]:
        q = query.lower()
        out = []
        for item in self._conv.get(role_id, []):
            if q in item["content"].lower():
                out.append({"id": item["id"], "content": item["content"], "score": 1.0, "metadata": item["metadata"]})
        return out[:max_items]

    def add_knowledge(
        self, role_id: str, content: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        item = {"id": str(uuid4()), "content": content, "metadata": metadata or {}}
        self._ku.setdefault(role_id, []).append(item)
        return item["id"]

    def search_knowledge(self, role_id: str, query: str, max_items: int = 10) -> List[Dict[str, Any]]:
        q = query.lower()
        out = []
        for item in self._ku.get(role_id, []):
            if q in item["content"].lower():
                out.append({"id": item["id"], "content": item["content"], "score": 1.0, "metadata": item["metadata"]})
        return out[:max_items]

    def archive_knowledge(self, role_id: str, knowledge_units: List[Dict[str, Any]]) -> str:
        del role_id, knowledge_units
        return f"archive_{uuid4()}"

    def health_check(self) -> Dict[str, Any]:
        return {"status": "ok", "details": {"provider": "sample_memory_plugin"}}
