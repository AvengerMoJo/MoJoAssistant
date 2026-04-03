from app.roles.role_designer import RoleDesignSession, _extract_name, _slugify_role_id


def test_extract_name_from_labeled_intro():
    assert _extract_name("Name: Bao\nHe is an ops-focused helper.") == "Bao"


def test_extract_name_from_named_phrase():
    assert _extract_name("A careful operator named Bao who automates workflows.") == "Bao"


def test_slugify_role_id_strips_punctuation():
    assert _slugify_role_id("Name:") == "name"
    assert _slugify_role_id("Bao Ops") == "bao_ops"


def test_role_spec_uses_extracted_name_and_safe_id():
    session = RoleDesignSession(session_id="test1234")
    session.submit_answer("Name: Bao\nHe is an ops-focused helper.")
    session.answers.update(
        {
            "core_values": "Bao values automation and uptime.",
            "emotional_reaction": "Bao stays calm under pressure.",
            "cognitive_style": "Bao thinks step by step.",
            "social_orientation": "Bao is direct and concise.",
            "adaptability": "Bao adapts quickly to new systems.",
            "purpose": "Bao handles infrastructure tasks.",
            "role_type": "ops",
            "predict_verify": "yes",
        }
    )

    spec = session._build_role_spec()

    assert spec["name"] == "Bao"
    assert spec["id"] == "bao"
