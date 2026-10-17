from app.llm.unified_client import no_choices_message


def test_provider_error_text_and_code_are_kept():
    d = {"error": {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 503}}
    assert no_choices_message(d) == "LLM returned no choices: Upstream error from Nvidia: Service temporarily overloaded (code 503)"


def test_reply_without_error_field_says_so():
    assert "no error field" in no_choices_message({"id": "x"})
