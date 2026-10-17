import pytest

from app.scheduler.role_template_engine import RoleTemplateEngine


@pytest.mark.parametrize("field", ["success_patterns", "escalation_rules"])
def test_role_field_of_the_wrong_type_is_named_in_the_error(field):
    with pytest.raises(ValueError, match=f"role 'quinn': '{field}' must be an object, got list"):
        RoleTemplateEngine().build({"id": "quinn", "name": "Quinn", field: ["a"]})
