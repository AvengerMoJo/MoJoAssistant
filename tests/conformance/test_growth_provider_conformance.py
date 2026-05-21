"""Growth provider conformance tests.

Covers both the ABC contract (via MockGrowthProvider) and the real
BonsaiGrowthModule adapter.
"""

import pytest
from app.services.provider_contracts import GrowthProvider, GrowthSnapshot, ProviderVersion


# ---------------------------------------------------------------------------
# Mock — proves the contract shape is implementable
# ---------------------------------------------------------------------------

class MockGrowthProvider(GrowthProvider):
    def get_version(self) -> ProviderVersion:
        return ProviderVersion("mock_growth", "1.0.0", "1.0")

    def snapshot(self, role_id: str, context=None) -> GrowthSnapshot:
        return GrowthSnapshot(
            role_id=role_id,
            timestamp="2026-01-01T00:00:00",
            dimensions={"core_values": {"score": 75}},
            metadata={"version": 0},
        )

    def evaluate(self, role_id: str, signals):
        return {
            "role_id": role_id,
            "current_dimensions": {},
            "proposed_dimensions": {"core_values": {"score": 80}},
            "validation": {"valid": True, "issues": [], "warnings": []},
            "signal_count": 1,
        }

    def propose(self, role_id: str, evaluation):
        return {
            "role_id": role_id,
            "snapshot_version": 1,
            "report": "# Growth Report",
            "proposed_dimensions": evaluation.get("proposed_dimensions", {}),
            "validation": evaluation.get("validation", {}),
        }

    def validate(self, role_id: str, proposal, decision: str):
        return {
            "status": "accepted" if decision == "accept" else "rejected",
            "decision": decision,
            "role_id": role_id,
        }

    def health_check(self):
        return {"status": "ok", "details": {"provider": "mock_growth"}}


# ---------------------------------------------------------------------------
# Contract tests (parametrized over mock + real adapter)
# ---------------------------------------------------------------------------

def _get_providers():
    providers = [MockGrowthProvider()]
    try:
        from app.scheduler.growth_provider import BonsaiGrowthModule
        providers.append(BonsaiGrowthModule())
    except Exception:
        pass
    return providers


@pytest.fixture(params=_get_providers(), ids=lambda p: p.get_version().provider_name)
def provider(request) -> GrowthProvider:
    return request.param


class TestGrowthProviderContract:
    def test_is_growth_provider(self, provider):
        assert isinstance(provider, GrowthProvider)

    def test_get_version_shape(self, provider):
        v = provider.get_version()
        assert isinstance(v, ProviderVersion)
        assert v.provider_name
        assert v.contract_version

    def test_snapshot_returns_growth_snapshot(self, provider):
        snap = provider.snapshot("test_role")
        assert isinstance(snap, GrowthSnapshot)
        assert snap.role_id == "test_role"
        assert isinstance(snap.timestamp, str) and snap.timestamp
        assert isinstance(snap.dimensions, dict)
        assert isinstance(snap.metadata, dict)

    def test_evaluate_returns_dict_with_required_keys(self, provider):
        signals = {"dimension": "core_values", "direction": "up", "strength": 0.5, "reason": "test"}
        result = provider.evaluate("test_role", signals)
        assert isinstance(result, dict)
        assert "role_id" in result
        assert "proposed_dimensions" in result
        assert result["role_id"] == "test_role"

    def test_evaluate_accepts_signals_list(self, provider):
        signals = [{"dimension": "core_values", "direction": "up", "strength": 0.3, "reason": "x"}]
        result = provider.evaluate("test_role", {"signals": signals})
        assert "proposed_dimensions" in result

    def test_propose_returns_dict_with_required_keys(self, provider):
        evaluation = {
            "role_id": "test_role",
            "proposed_dimensions": {"core_values": {"score": 80}},
            "validation": {"valid": True, "issues": [], "warnings": []},
        }
        proposal = provider.propose("test_role", evaluation)
        assert isinstance(proposal, dict)
        assert "role_id" in proposal
        assert "snapshot_version" in proposal
        assert "report" in proposal

    def test_validate_accept(self, provider):
        proposal = {"role_id": "test_role", "snapshot_version": 1}
        result = provider.validate("test_role", proposal, "accept")
        assert isinstance(result, dict)
        assert result.get("decision") == "accept"

    def test_validate_reject(self, provider):
        proposal = {"role_id": "test_role", "snapshot_version": 1}
        result = provider.validate("test_role", proposal, "reject")
        assert isinstance(result, dict)
        assert result.get("decision") == "reject"

    def test_health_check_returns_status(self, provider):
        h = provider.health_check()
        assert isinstance(h, dict)
        assert "status" in h
        assert h["status"] in ("ok", "error", "degraded")

    def test_optional_snapshot_lifecycle_helpers(self, provider):
        # Optional extension: providers may expose snapshot history + recall.
        if provider.get_version().provider_name != "bonsai_growth":
            return

        evaluation = provider.evaluate(
            "test_role",
            {"dimension": "core_values", "direction": "up", "strength": 0.4},
        )
        proposal = provider.propose("test_role", evaluation)
        v = int(proposal["snapshot_version"])

        snapshots = provider.list_snapshots("test_role")
        assert isinstance(snapshots, list)
        assert any(int(s.get("version", -1)) == v for s in snapshots)

        recalled = provider.recall_snapshot("test_role", v, pin=True)
        assert recalled.get("status") == "success"
        assert int(recalled.get("snapshot_version", -1)) == v


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestGrowthRegistry:
    def test_resolve_growth_provider(self):
        from app.services.provider_contracts import get_registry
        provider = get_registry().resolve_growth_provider()
        assert isinstance(provider, GrowthProvider)

    def test_resolve_returns_bonsai_by_default(self):
        from app.services.provider_contracts import get_registry
        provider = get_registry().resolve_growth_provider()
        assert provider.get_version().provider_name == "bonsai_growth"

    def test_register_custom_growth_provider(self):
        from app.services.provider_contracts import get_registry
        registry = get_registry()
        registry.register_growth_provider("mock_growth_reg", MockGrowthProvider)
        provider = registry.resolve_growth_provider("mock_growth_reg")
        assert provider.get_version().provider_name == "mock_growth"
