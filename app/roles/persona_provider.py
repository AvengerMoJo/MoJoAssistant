"""Default PersonaModule implementation (agency-agents backed)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.roles.agency_importer import list_available_personas, parse_agency_persona
from app.services.provider_contracts import (
    PersonaProvider,
    PersonaScore,
    PersonaSpec,
    PersonaSummary,
    ProviderVersion,
)


class AgencyPersonaModule(PersonaProvider):
    PROVIDER_NAME = "agency_persona"
    PROVIDER_VERSION = "1.0.0"
    CONTRACT_VERSION = "1.0"

    def get_version(self) -> ProviderVersion:
        return ProviderVersion(
            provider_name=self.PROVIDER_NAME,
            provider_version=self.PROVIDER_VERSION,
            contract_version=self.CONTRACT_VERSION,
        )

    def generate(self, spec: PersonaSpec) -> Dict[str, Any]:
        if spec.persona_file:
            role = parse_agency_persona(Path(spec.persona_file))
        else:
            role_id = spec.name.lower().replace(" ", "_")
            role = {
                "id": role_id,
                "name": spec.name,
                "purpose": spec.purpose,
                "capabilities": spec.capabilities or ["memory"],
                "nine_chapter_score": 75,
                "dimensions": {},
                "agent_type": "general",
            }

        if spec.metadata:
            role.update({"persona_metadata": spec.metadata})

        return role

    def score(self, role_def: Dict[str, Any]) -> PersonaScore:
        dims = role_def.get("dimensions") or {}
        if dims:
            values = []
            for v in dims.values():
                if isinstance(v, dict):
                    values.append(int(v.get("score", 0)))
                elif isinstance(v, (int, float)):
                    values.append(int(v))
            total = int(sum(values) / len(values)) if values else int(role_def.get("nine_chapter_score", 75))
        else:
            total = int(role_def.get("nine_chapter_score", 75))

        return PersonaScore(total_score=total, dimensions=dims, confidence=0.75)

    def list_personas(self, filter: Optional[Dict[str, Any]] = None) -> List[PersonaSummary]:
        filter = filter or {}
        cat_filter = str(filter.get("category", "")).strip().lower()
        name_q = str(filter.get("query", "")).strip().lower()

        items = list_available_personas()
        out: List[PersonaSummary] = []
        for p in items:
            category = str(p.get("category", "general"))
            name = str(p.get("name", ""))
            if cat_filter and category.lower() != cat_filter:
                continue
            if name_q and name_q not in name.lower():
                continue
            out.append(
                PersonaSummary(
                    id=name.lower().replace(" ", "_") or "persona",
                    name=name,
                    category=category,
                    description=str(p.get("description", "")),
                    source=str(p.get("path", "")),
                )
            )
        return out

    def health_check(self) -> Dict[str, Any]:
        try:
            count = len(self.list_personas())
            return {
                "status": "ok",
                "details": {
                    "provider": self.PROVIDER_NAME,
                    "persona_count": count,
                },
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
