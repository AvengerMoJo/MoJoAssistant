"""Conformance tests for pluggable embedding backends."""

from __future__ import annotations

from mojo_memory.embeddings.registry import create_backend, list_backends, register_backend
from mojo_memory.embeddings.backends.base import EmbeddingBackend


class MockEmbeddingBackend(EmbeddingBackend):
    def __init__(self, model_name: str = "mock", embedding_dim: int = 8, **kwargs):
        del kwargs
        self.model_name = model_name
        self.embedding_dim = embedding_dim

    def get_text_embedding(self, text: str, prompt_name: str = "passage"):
        del prompt_name
        base = float(len(text))
        return [base + i for i in range(self.embedding_dim)]

    def get_batch_embeddings(self, texts):
        return [self.get_text_embedding(t) for t in texts]

    def get_info(self):
        return {"backend": "mock", "model_name": self.model_name, "embedding_dim": self.embedding_dim}

    def change_model(self, model_name: str):
        self.model_name = model_name
        return True


def test_registry_has_default_backends():
    names = list_backends()
    assert "huggingface" in names
    assert "local" in names
    assert "random" in names


def test_random_backend_deterministic():
    backend = create_backend("random", model_name="random/test", embedding_dim=16)
    a = backend.get_text_embedding("hello")
    b = backend.get_text_embedding("hello")
    c = backend.get_text_embedding("world")
    assert a == b
    assert a != c
    assert len(a) == 16


def test_register_custom_backend():
    register_backend("mock_test", MockEmbeddingBackend)
    backend = create_backend("mock_test", model_name="mock/a", embedding_dim=4)
    emb = backend.get_text_embedding("abc")
    assert len(emb) == 4
    assert backend.get_info()["backend"] == "mock"


def test_simple_embedding_delegates_to_backend():
    from mojo_memory.memory.simplified_embeddings import SimpleEmbedding

    register_backend("mock_for_simple", MockEmbeddingBackend)
    emb = SimpleEmbedding(backend="mock_for_simple", model_name="mock/x", embedding_dim=6)
    vec = emb.get_text_embedding("abcdef")
    assert len(vec) == 6
    info = emb.get_model_info()
    assert info["model_name"] == "mock/x"
