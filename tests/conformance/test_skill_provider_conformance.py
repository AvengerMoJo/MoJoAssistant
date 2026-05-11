"""Skill provider conformance tests.

Covers both the ABC contract (MockSkillProvider) and the real DefaultSkillProvider.
"""

import pytest
from app.services.provider_contracts import (
    InstallResult,
    ProviderVersion,
    SkillBlueprint,
    SkillProvider,
    SkillTestResult,
)


# ---------------------------------------------------------------------------
# Mock — proves the ABC is implementable without file I/O
# ---------------------------------------------------------------------------

_MOCK_BP = SkillBlueprint(
    id="mock_skill",
    name="Mock Skill",
    description="A test skill that does nothing.",
    category="exec",
    danger_level="low",
    version="1.0.0",
    parameters={"type": "object", "properties": {}, "required": []},
    executor_template={"type": "builtin"},
    test_args={},
)


class MockSkillProvider(SkillProvider):
    def get_version(self) -> ProviderVersion:
        return ProviderVersion("mock_skill", "1.0.0", "1.0")

    def catalog(self, filter=None) -> list:
        return [_MOCK_BP]

    def blueprint(self, skill_id: str):
        return _MOCK_BP if skill_id == "mock_skill" else None

    def install(self, skill_id: str, env=None) -> InstallResult:
        return InstallResult(
            skill_id=skill_id,
            tool_entry={"name": skill_id, "executor": {"type": "builtin"}},
            env_used=env or {},
            installed_at="2026-01-01T00:00:00",
        )

    def install_blueprint(self, blueprint, env=None) -> InstallResult:
        return InstallResult(
            skill_id=blueprint.get("id", "unknown"),
            tool_entry={"name": blueprint.get("id"), "executor": blueprint.get("executor_template", {})},
            env_used=env or {},
            installed_at="2026-01-01T00:00:00",
            blueprint_saved_at="/tmp/mock.json",
        )

    def uninstall(self, skill_id: str) -> bool:
        return True

    def test(self, skill_id: str) -> SkillTestResult:
        return SkillTestResult(skill_id=skill_id, passed=True, output="mock ok")

    def search(self, query: str) -> list:
        return [_MOCK_BP] if query.lower() in "mock skill" else []

    def health_check(self):
        return {"status": "ok", "details": {"provider": "mock_skill"}}


# ---------------------------------------------------------------------------
# Contract tests (parametrized over mock + real DefaultSkillProvider)
# ---------------------------------------------------------------------------

def _get_providers():
    providers = [MockSkillProvider()]
    try:
        from app.scheduler.skill_provider import DefaultSkillProvider
        providers.append(DefaultSkillProvider())
    except Exception:
        pass
    return providers


@pytest.fixture(params=_get_providers(), ids=lambda p: p.get_version().provider_name)
def provider(request) -> SkillProvider:
    return request.param


class TestSkillProviderContract:
    def test_is_skill_provider(self, provider):
        assert isinstance(provider, SkillProvider)

    def test_get_version_shape(self, provider):
        v = provider.get_version()
        assert isinstance(v, ProviderVersion)
        assert v.provider_name and v.contract_version

    def test_catalog_returns_list(self, provider):
        items = provider.catalog()
        assert isinstance(items, list)

    def test_catalog_items_are_blueprints(self, provider):
        items = provider.catalog()
        for bp in items:
            assert isinstance(bp, SkillBlueprint)
            assert bp.id and bp.name and bp.description

    def test_catalog_filter_by_category(self, provider):
        all_items = provider.catalog()
        if not all_items:
            pytest.skip("no blueprints in catalog")
        cat = all_items[0].category
        filtered = provider.catalog({"category": cat})
        assert all(b.category == cat for b in filtered)

    def test_blueprint_returns_skill_blueprint(self, provider):
        items = provider.catalog()
        if not items:
            pytest.skip("no blueprints in catalog")
        bp = provider.blueprint(items[0].id)
        assert isinstance(bp, SkillBlueprint)
        assert bp.id == items[0].id

    def test_blueprint_unknown_returns_none(self, provider):
        assert provider.blueprint("nonexistent_skill_xyz") is None

    def test_search_returns_list(self, provider):
        results = provider.search("skill")
        assert isinstance(results, list)

    def test_install_blueprint_returns_install_result(self, provider):
        bp_dict = {
            "id": "conformance_test_skill",
            "name": "Conformance Test Skill",
            "description": "Installed by conformance test.",
            "category": "exec",
            "danger_level": "low",
            "version": "1.0.0",
            "parameters": {"type": "object", "properties": {}, "required": []},
            "executor_template": {"type": "builtin"},
            "test_args": {},
        }
        result = provider.install_blueprint(bp_dict, {})
        assert isinstance(result, InstallResult)
        assert result.skill_id == "conformance_test_skill"
        assert isinstance(result.tool_entry, dict)
        assert result.installed_at
        # Cleanup
        provider.uninstall("conformance_test_skill")

    def test_uninstall_returns_bool(self, provider):
        assert isinstance(provider.uninstall("nonexistent_skill_xyz"), bool)

    def test_test_returns_skill_test_result(self, provider):
        items = provider.catalog()
        if not items:
            pytest.skip("no blueprints in catalog")
        result = provider.test(items[0].id)
        assert isinstance(result, SkillTestResult)
        assert isinstance(result.passed, bool)
        assert isinstance(result.output, str)

    def test_health_check_returns_status(self, provider):
        h = provider.health_check()
        assert isinstance(h, dict)
        assert h.get("status") in ("ok", "degraded", "error")


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestSkillRegistry:
    def test_resolve_skill_provider(self):
        from app.services.provider_contracts import get_registry
        provider = get_registry().resolve_skill_provider()
        assert isinstance(provider, SkillProvider)

    def test_resolve_returns_default_by_default(self):
        from app.services.provider_contracts import get_registry
        provider = get_registry().resolve_skill_provider()
        assert provider.get_version().provider_name == "default_skill"

    def test_register_custom_skill_provider(self):
        from app.services.provider_contracts import get_registry
        registry = get_registry()
        registry.register_skill_provider("mock_skill_reg", MockSkillProvider)
        provider = registry.resolve_skill_provider("mock_skill_reg")
        assert provider.get_version().provider_name == "mock_skill"


# ---------------------------------------------------------------------------
# Blueprint file validation
# ---------------------------------------------------------------------------

class TestSystemBlueprints:
    def test_system_blueprints_load_cleanly(self):
        from app.scheduler.skill_provider import DefaultSkillProvider
        p = DefaultSkillProvider()
        items = p.catalog()
        assert len(items) >= 1, "Expected at least one system blueprint in config/skill_blueprints/"

    def test_blueprints_have_executor_template(self):
        from app.scheduler.skill_provider import DefaultSkillProvider
        p = DefaultSkillProvider()
        for bp in p.catalog():
            assert bp.executor_template, f"Blueprint '{bp.id}' missing executor_template"

    def test_blueprints_have_parameters(self):
        from app.scheduler.skill_provider import DefaultSkillProvider
        p = DefaultSkillProvider()
        for bp in p.catalog():
            assert isinstance(bp.parameters, dict), f"Blueprint '{bp.id}' parameters must be a dict"
