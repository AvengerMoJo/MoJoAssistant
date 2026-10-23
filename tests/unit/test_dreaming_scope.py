"""Where a dreaming run's text may travel depends on where it came from (owner chat vs task output)."""
import pytest

from app.scheduler.dreaming_scope import resolve_scope

CFG = {"max_data_scope": "own_network", "scopes": {"task_output": "third_party"}}


def test_owner_conversations_stay_on_the_owners_network():
    assert resolve_scope(CFG, "conversation") == "own_network"


def test_task_output_may_go_wider_when_configured():
    assert resolve_scope(CFG, "task_output") == "third_party"


def test_nothing_configured_means_own_network():
    assert resolve_scope({}, "task_output") == "own_network"
    assert resolve_scope(None, "conversation") == "own_network"


def test_a_role_with_a_narrower_data_scope_caps_its_task_output():
    assert resolve_scope(CFG, "task_output", "own_network") == "own_network"
    assert resolve_scope(CFG, "task_output", "local_host") == "local_host"


def test_a_role_scope_never_widens_the_configured_one():
    assert resolve_scope(CFG, "conversation", "third_party") == "own_network"


@pytest.mark.parametrize("cfg,source,role", [
    ({}, "chat", None),
    ({"scopes": {"task_output": "everywhere"}}, "task_output", None),
    ({}, "conversation", "mars"),
])
def test_unknown_names_are_errors_not_a_wider_scope(cfg, source, role):
    with pytest.raises(ValueError):
        resolve_scope(cfg, source, role)
