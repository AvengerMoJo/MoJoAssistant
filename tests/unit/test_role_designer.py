from app.roles.role_designer import RoleDesignSession, _extract_name, _slugify_role_id


def test_extract_name_from_labeled_intro():
    assert _extract_name("Name: Provisioner\nHe is an ops-focused helper.") == "Provisioner"


def test_extract_name_from_named_phrase():
    assert _extract_name("A careful operator named Provisioner who automates workflows.") == "Provisioner"


def test_slugify_role_id_strips_punctuation():
    assert _slugify_role_id("Name:") == "name"
    assert _slugify_role_id("Provisioner Ops") == "provisioner_ops"


def test_role_spec_uses_extracted_name_and_safe_id():
    session = RoleDesignSession(session_id="test1234")
    session.submit_answer("Name: Provisioner\nHe is an ops-focused helper.")
    session.answers.update(
        {
            "core_values": "Provisioner values automation and uptime.",
            "emotional_reaction": "Provisioner stays calm under pressure.",
            "cognitive_style": "Provisioner thinks step by step.",
            "social_orientation": "Provisioner is direct and concise.",
            "adaptability": "Provisioner adapts quickly to new systems.",
            "purpose": "Provisioner handles infrastructure tasks.",
            "role_type": "ops",
            "predict_verify": "yes",
        }
    )

    spec = session._build_role_spec()

    assert spec["name"] == "Provisioner"
    assert spec["id"] == "provisioner"
