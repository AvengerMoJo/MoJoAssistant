"""Sample persona provider plugin implementation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.provider_contracts import PersonaProvider, PersonaScore, PersonaSpec, PersonaSummary, ProviderVersion


class PluginProvider(PersonaProvider):
    def get_version(self) -> ProviderVersion:
        return ProviderVersion("sample_persona_plugin", "0.1.0", "1.0")

    def generate(self, spec: PersonaSpec) -> Dict[str, Any]:
        return {
            "id": f"persona_{spec.name.lower().replace(' ', '_')}",
            "name": spec.name,
            "purpose": spec.purpose,
            "capabilities": spec.capabilities,
            "metadata": spec.metadata,
        }

    def score(self, role_def: Dict[str, Any]) -> PersonaScore:
        del role_def
        return PersonaScore(total_score=75, dimensions={"clarity": {"score": 75}}, confidence=0.8)

    def list_personas(self, filter: Optional[Dict[str, Any]] = None) -> List[PersonaSummary]:
        del filter
        return [
            PersonaSummary(
                id="sample_persona",
                name="Sample Persona",
                category="example",
                description="Example persona from Plugin SDK sample package",
                source="sample_persona_plugin",
            )
        ]
