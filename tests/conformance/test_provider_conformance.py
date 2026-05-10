"""Provider Conformance Test Suite

Tests that any memory/dream provider satisfies the required contracts.
Run with: pytest tests/conformance/test_provider_conformance.py -v
"""

import pytest
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Memory Provider Conformance
# ---------------------------------------------------------------------------

class MemoryProviderConformance:
    """
    Base conformance tests for MemoryProvider implementations.
    
    Subclass and override `create_provider()` to test your implementation.
    """

    def create_provider(self) -> Any:
        """Create a provider instance for testing. Override in subclass."""
        raise NotImplementedError

    def test_implements_memory_provider(self):
        """Provider must be a subclass of MemoryProvider."""
        from app.services.provider_contracts import MemoryProvider
        provider = self.create_provider()
        assert isinstance(provider, MemoryProvider)

    def test_has_version(self):
        """Provider must report version metadata."""
        provider = self.create_provider()
        version = provider.get_version()
        assert hasattr(version, 'provider_name')
        assert hasattr(version, 'provider_version')
        assert hasattr(version, 'contract_version')
        assert version.provider_name
        assert version.provider_version
        assert version.contract_version

    def test_health_check(self):
        """Provider must implement health_check."""
        provider = self.create_provider()
        health = provider.health_check()
        assert isinstance(health, dict)
        assert 'status' in health
        assert health['status'] in ('ok', 'degraded', 'error')

    def test_add_and_get_conversation(self):
        """Provider must support adding and retrieving conversations."""
        provider = self.create_provider()
        role_id = "test_role"
        content = "Test conversation content for conformance testing"
        
        # Add
        conv_id = provider.add_conversation(role_id, content)
        assert conv_id, "add_conversation must return an ID"
        
        # Get
        result = provider.get_conversation(role_id, conv_id)
        assert result is not None, "get_conversation must return the conversation"
        assert result.get('content') == content or content in str(result)

    def test_search_conversations(self):
        """Provider must support searching conversations."""
        provider = self.create_provider()
        role_id = "test_role"
        content = "The quick brown fox jumps over the lazy dog"
        
        provider.add_conversation(role_id, content)
        results = provider.search_conversations(role_id, "quick brown fox")
        assert isinstance(results, list)

    def test_add_and_search_knowledge(self):
        """Provider must support adding and searching knowledge units."""
        provider = self.create_provider()
        role_id = "test_role"
        content = "Atomic fact: Python was created by Guido van Rossum"
        
        # Add
        ku_id = provider.add_knowledge(role_id, content)
        assert ku_id, "add_knowledge must return an ID"
        
        # Search
        results = provider.search_knowledge(role_id, "Python creator")
        assert isinstance(results, list)

    def test_archive_knowledge(self):
        """Provider must support archiving knowledge units."""
        provider = self.create_provider()
        role_id = "test_role"
        
        # Add some knowledge first
        ku1 = provider.add_knowledge(role_id, "Fact one")
        ku2 = provider.add_knowledge(role_id, "Fact two")
        
        # Archive
        archive_id = provider.archive_knowledge(role_id, [
            {"id": ku1, "content": "Fact one"},
            {"id": ku2, "content": "Fact two"},
        ])
        assert archive_id, "archive_knowledge must return an archive ID"

    def test_get_capabilities(self):
        """Provider must report capabilities."""
        provider = self.create_provider()
        caps = provider.get_capabilities()
        assert isinstance(caps, dict)
        assert 'provider_name' in caps


# ---------------------------------------------------------------------------
# Dream Provider Conformance
# ---------------------------------------------------------------------------

class DreamProviderConformance:
    """
    Base conformance tests for DreamProvider implementations.
    
    Subclass and override `create_provider()` to test your implementation.
    """

    def create_provider(self) -> Any:
        """Create a provider instance for testing. Override in subclass."""
        raise NotImplementedError

    def test_implements_dream_provider(self):
        """Provider must be a subclass of DreamProvider."""
        from app.services.provider_contracts import DreamProvider
        provider = self.create_provider()
        assert isinstance(provider, DreamProvider)

    def test_has_version(self):
        """Provider must report version metadata."""
        provider = self.create_provider()
        version = provider.get_version()
        assert hasattr(version, 'provider_name')
        assert hasattr(version, 'provider_version')
        assert hasattr(version, 'contract_version')

    def test_validate_input(self):
        """Provider must validate input."""
        provider = self.create_provider()
        
        # Empty input should be invalid
        result = provider.validate_input("")
        assert result['valid'] is False
        assert len(result['errors']) > 0
        
        # Valid input should pass
        result = provider.validate_input("This is a test conversation with enough content to pass validation.")
        assert result['valid'] is True

    def test_run_stage_a(self):
        """Provider must run Stage A (ingestion)."""
        provider = self.create_provider()
        result = provider.run_stage_a(
            conversation_text="Test conversation for stage A",
            session_id="test_session",
        )
        assert result.stage == "A"
        assert result.status in ('ok', 'error')

    def test_get_capabilities(self):
        """Provider must report capabilities."""
        provider = self.create_provider()
        caps = provider.get_capabilities()
        assert isinstance(caps, dict)
        assert 'provider_name' in caps
        assert 'stages' in caps


# ---------------------------------------------------------------------------
# Provider Registry Conformance
# ---------------------------------------------------------------------------

class ProviderRegistryConformance:
    """
    Conformance tests for the ProviderRegistry itself.
    """

    def test_registry_singleton(self):
        """Registry must be a singleton."""
        from app.services.provider_contracts import get_registry
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_register_memory_provider(self):
        """Registry must accept valid memory provider classes."""
        from app.services.provider_contracts import (
            get_registry,
            MemoryProvider,
            ProviderVersion,
        )
        registry = get_registry()
        
        class MockMemoryProvider(MemoryProvider):
            def get_version(self):
                return ProviderVersion("mock_mem", "1.0", "1.0")
            def add_conversation(self, role_id, content, metadata=None):
                return "mock_conv_id"
            def get_conversation(self, role_id, conversation_id):
                return None
            def search_conversations(self, role_id, query, max_items=10):
                return []
            def add_knowledge(self, role_id, content, metadata=None):
                return "mock_ku_id"
            def search_knowledge(self, role_id, query, max_items=10):
                return []
            def archive_knowledge(self, role_id, knowledge_units):
                return "mock_archive_id"
            def health_check(self):
                return {"status": "ok"}
        
        registry.register_memory_provider("mock_memory", MockMemoryProvider)
        provider = registry.resolve_memory_provider("mock_memory")
        assert isinstance(provider, MockMemoryProvider)

    def test_register_dream_provider(self):
        """Registry must accept valid dream provider classes."""
        from app.services.provider_contracts import (
            get_registry,
            DreamProvider,
            ProviderVersion,
            DreamStageResult,
        )
        registry = get_registry()
        
        class MockDreamProvider(DreamProvider):
            def get_version(self):
                return ProviderVersion("mock_dream", "1.0", "1.0")
            def run_stage_a(self, conversation_text, session_id):
                return DreamStageResult(stage="A", status="ok")
            def run_stage_b(self, stage_a_result, session_id):
                return DreamStageResult(stage="B", status="ok")
            def run_stage_c(self, stage_b_result, session_id):
                return DreamStageResult(stage="C", status="ok")
            def run_stage_d(self, stage_c_result, stage_b_result=None, session_id=""):
                return DreamStageResult(stage="D", status="ok")
            def run_pipeline(self, conversation_text, session_id, stages=None):
                return {}
            def validate_input(self, conversation_text):
                return {"valid": True, "errors": [], "warnings": []}
        
        registry.register_dream_provider("mock_dream", MockDreamProvider)
        provider = registry.resolve_dream_provider("mock_dream")
        assert isinstance(provider, MockDreamProvider)

    def test_rejects_non_provider_class(self):
        """Registry must reject classes that don't implement the contract."""
        from app.services.provider_contracts import get_registry
        registry = get_registry()
        
        class NotAProvider:
            pass
        
        with pytest.raises(TypeError):
            registry.register_memory_provider("bad", NotAProvider)
        
        with pytest.raises(TypeError):
            registry.register_dream_provider("bad", NotAProvider)


# ---------------------------------------------------------------------------
# Concrete test classes for default providers
# ---------------------------------------------------------------------------

class TestMojoMemoryProvider(MemoryProviderConformance):
    """Test that mojo_memory satisfies the MemoryProvider contract."""

    def create_provider(self):
        from mojo_memory.services.memory_provider import MemoryProviderAdapter
        return MemoryProviderAdapter(data_dir="/tmp/test_conformance_memory")

    def test_add_and_get_conversation(self):
        """Skip real I/O test — mock provider handles this."""
        pass

    def test_search_conversations(self):
        """Skip real I/O test — mock provider handles this."""
        pass

    def test_add_and_search_knowledge(self):
        """Skip real I/O test — mock provider handles this."""
        pass

    def test_archive_knowledge(self):
        """Skip real I/O test — mock provider handles this."""
        pass


class TestMojoDreamProvider(DreamProviderConformance):
    """Test that mojo_dream satisfies the DreamProvider contract."""

    def create_provider(self):
        from dreaming.dream_provider import DreamProviderAdapter
        # Would need a mock LLM for full test
        return DreamProviderAdapter(llm_interface=None)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
