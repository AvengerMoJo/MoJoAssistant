"""Plugin matrix tests: default provider(s) + mock alternatives."""

from app.services.provider_contracts import (
    DreamProvider,
    DreamStageResult,
    MemoryProvider,
    PersonaProvider,
    PersonaScore,
    PersonaSpec,
    ProviderVersion,
    get_registry,
)


class MockAltMemory(MemoryProvider):
    def get_version(self):
        return ProviderVersion("alt_memory", "1.0.0", "1.0")
    def add_conversation(self, role_id, content, metadata=None):
        return "c1"
    def get_conversation(self, role_id, conversation_id):
        return {"id": conversation_id, "content": "x"}
    def search_conversations(self, role_id, query, max_items=10):
        return []
    def add_knowledge(self, role_id, content, metadata=None):
        return "k1"
    def search_knowledge(self, role_id, query, max_items=10):
        return []
    def archive_knowledge(self, role_id, knowledge_units):
        return "a1"
    def health_check(self):
        return {"status": "ok"}


class MockAltDream(DreamProvider):
    def get_version(self):
        return ProviderVersion("alt_dream", "1.0.0", "1.0")
    def run_stage_a(self, conversation_text, session_id):
        return DreamStageResult(stage="A", status="ok")
    def run_stage_b(self, stage_a_result, session_id):
        return DreamStageResult(stage="B", status="ok")
    def run_stage_c(self, stage_b_result, session_id):
        return DreamStageResult(stage="C", status="ok")
    def run_stage_d(self, stage_c_result, stage_b_result=None, session_id=""):
        return DreamStageResult(stage="D", status="ok")
    def run_pipeline(self, conversation_text, session_id, stages=None):
        return {"A": DreamStageResult(stage="A", status="ok")}
    def validate_input(self, conversation_text):
        return {"valid": True, "errors": [], "warnings": []}


class MockAltPersona(PersonaProvider):
    def get_version(self):
        return ProviderVersion("alt_persona", "1.0.0", "1.0")
    def generate(self, spec: PersonaSpec):
        return {"id": "r1", "name": spec.name, "purpose": spec.purpose}
    def score(self, role_def):
        return PersonaScore(total_score=80)
    def list_personas(self, filter=None):
        return []


def test_plugin_matrix_default_and_mock_registration():
    r = get_registry()
    # default discover path should not crash
    r.discover_modules()

    # register alternates
    r.register_memory_provider("alt_memory", MockAltMemory)
    r.register_dream_provider("alt_dream", MockAltDream)
    r.register_persona_provider("alt_persona", MockAltPersona)

    m = r.resolve_memory_provider("alt_memory")
    d = r.resolve_dream_provider("alt_dream")
    p = r.resolve_persona_provider("alt_persona")

    assert m.get_version().provider_name == "alt_memory"
    assert d.get_version().provider_name == "alt_dream"
    assert p.get_version().provider_name == "alt_persona"
