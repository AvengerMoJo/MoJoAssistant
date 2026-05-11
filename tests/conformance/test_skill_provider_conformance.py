"""Skill provider conformance skeleton."""

from app.services.provider_contracts import SkillProvider, ProviderVersion


class MockSkillProvider(SkillProvider):
    def get_version(self) -> ProviderVersion:
        return ProviderVersion("mock_skill", "1.0.0", "1.0")

    def catalog(self):
        return [{"id": "skill_a", "name": "Skill A"}]

    def blueprint(self, skill_id: str):
        return {"id": skill_id, "template": "echo hi"}

    def install(self, skill_id: str, env):
        return {"status": "installed", "skill_id": skill_id, "env": env}

    def test(self, skill_id: str):
        return {"status": "ok", "skill_id": skill_id}


def test_skill_provider_contract_skeleton():
    p = MockSkillProvider()
    assert isinstance(p, SkillProvider)
    assert p.catalog()
    assert p.blueprint("skill_a")["id"] == "skill_a"
    assert p.install("skill_a", {"MEMORY_PATH": "/tmp"})["status"] == "installed"
    assert p.test("skill_a")["status"] == "ok"
