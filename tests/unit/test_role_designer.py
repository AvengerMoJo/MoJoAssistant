from unittest.mock import patch

from app.roles.role_designer import RoleDesignSession, _extract_name, _slugify_role_id


def _run_to_synthesis(session: RoleDesignSession) -> None:
    answers = {
        "intro": "Name: Provisioner\nHe is an ops-focused helper.",
        "core_values": "Provisioner values automation and uptime.",
        "emotional_reaction": "Provisioner stays calm under pressure.",
        "cognitive_style": "Provisioner thinks step by step.",
        "social_orientation": "Provisioner is direct and concise.",
        "adaptability": "Provisioner adapts quickly to new systems.",
        "purpose": "Provisioner handles infrastructure tasks.",
        "role_type": "ops",
        "capabilities": "exec,file",
        "predict_verify": "yes",
    }
    for step in ["intro", "core_values", "emotional_reaction", "cognitive_style",
                 "social_orientation", "adaptability", "purpose", "role_type",
                 "capabilities", "predict_verify"]:
        session.submit_answer(answers[step])
    assert session.current_step == "synthesis"


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


class TestSynthesisPersistence:
    """2026-10-03: submit_answer() must persist the role itself on
    confirmation -- found live after two real role-creation attempts reached
    'complete' with nothing ever written to ~/.memory/roles/, because the
    only RoleManager().save() call lived in one specific MCP caller
    (tools.py's _execute_role_design_answer), not in the session itself."""

    def test_yes_at_synthesis_persists_via_role_manager(self):
        session = RoleDesignSession(session_id="test_persist")
        _run_to_synthesis(session)

        with patch("app.roles.role_manager.RoleManager.save", return_value="/fake/path/provisioner.json") as mock_save:
            next_step, payload = session.submit_answer("yes")

        assert next_step == "complete"
        mock_save.assert_called_once()
        saved_spec = mock_save.call_args[0][0]
        assert saved_spec["id"] == "provisioner"
        assert payload["_persisted"] == {"saved": True, "path": "/fake/path/provisioner.json"}

    def test_save_failure_is_reported_not_swallowed(self):
        session = RoleDesignSession(session_id="test_persist_fail")
        _run_to_synthesis(session)

        with patch("app.roles.role_manager.RoleManager.save", side_effect=ValueError("disk full")):
            next_step, payload = session.submit_answer("yes")

        assert next_step == "complete"
        assert payload["_persisted"]["saved"] is False
        assert "disk full" in payload["_persisted"]["error"]

    def test_non_yes_answer_does_not_persist_and_stays_at_synthesis(self):
        session = RoleDesignSession(session_id="test_no_confirm")
        _run_to_synthesis(session)

        with patch("app.roles.role_manager.RoleManager.save") as mock_save:
            next_step, payload = session.submit_answer("no: the purpose is wrong")

        mock_save.assert_not_called()
        assert next_step == "synthesis"
        assert session.current_step == "synthesis"
        assert "Not confirmed" in payload["message"]

    def test_adjust_reply_does_not_persist_either(self):
        """'adjust: ...' is advertised in the synthesis prompt but revision
        handling isn't implemented -- it must not silently complete/save."""
        session = RoleDesignSession(session_id="test_adjust")
        _run_to_synthesis(session)

        with patch("app.roles.role_manager.RoleManager.save") as mock_save:
            next_step, _ = session.submit_answer("adjust: make it more direct")

        mock_save.assert_not_called()
        assert next_step == "synthesis"
