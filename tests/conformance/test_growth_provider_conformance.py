"""Growth provider conformance skeleton."""

from app.services.provider_contracts import GrowthProvider, GrowthSnapshot, ProviderVersion


class MockGrowthProvider(GrowthProvider):
    def get_version(self) -> ProviderVersion:
        return ProviderVersion("mock_growth", "1.0.0", "1.0")

    def snapshot(self, role_id: str, context=None) -> GrowthSnapshot:
        return GrowthSnapshot(role_id=role_id, timestamp="2026-01-01T00:00:00Z")

    def evaluate(self, role_id: str, signals):
        return {"status": "ok", "signals": signals}

    def propose(self, role_id: str, evaluation):
        return {"proposal_id": "p1", "role_id": role_id, "evaluation": evaluation}

    def validate(self, role_id: str, proposal, decision: str):
        return {"status": "validated", "decision": decision, "role_id": role_id}


def test_growth_provider_contract_skeleton():
    p = MockGrowthProvider()
    assert isinstance(p, GrowthProvider)
    s = p.snapshot("role_a")
    assert s.role_id == "role_a"
    e = p.evaluate("role_a", {"delta": 1})
    pr = p.propose("role_a", e)
    v = p.validate("role_a", pr, "approve")
    assert v["status"] == "validated"
