from app.roles.persona_provider import AgencyPersonaModule
from app.services.provider_contracts import PersonaProvider, PersonaSpec


def test_agency_persona_implements_contract():
    p = AgencyPersonaModule()
    assert isinstance(p, PersonaProvider)


def test_agency_persona_generate_score_list():
    p = AgencyPersonaModule()
    role = p.generate(PersonaSpec(name='Test Persona', purpose='test purpose'))
    assert isinstance(role, dict)
    assert role.get('name')

    score = p.score(role)
    assert isinstance(score.total_score, int)
    assert 0 <= score.total_score <= 100

    personas = p.list_personas()
    assert isinstance(personas, list)
