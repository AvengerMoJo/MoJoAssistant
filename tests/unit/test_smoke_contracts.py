from app.scheduler.smoke_contracts import (
    ResourceContract,
    evaluate_resource_for_basic_agentic,
    evaluate_role_tools,
)


def test_resource_contract_passes_for_valid_resource():
    resource = {
        "enabled": True,
        "status": "available",
        "model": "qwen/qwen3.5-35b-a3b",
        "context_limit": 32768,
        "output_limit": 8192,
    }
    result = evaluate_resource_for_basic_agentic(resource)
    assert result.ok is True


def test_resource_contract_fails_for_unreachable_resource():
    resource = {
        "enabled": True,
        "status": "unreachable",
        "model": "qwen",
        "context_limit": 32768,
        "output_limit": 8192,
    }
    result = evaluate_resource_for_basic_agentic(resource)
    assert result.ok is False
    assert any(c.name == "reachable" and not c.ok for c in result.checks)


def test_resource_contract_fails_for_low_context():
    resource = {
        "enabled": True,
        "status": "available",
        "model": "qwen",
        "context_limit": 2048,
        "output_limit": 8192,
    }
    result = evaluate_resource_for_basic_agentic(resource, ResourceContract(min_context_limit=8192))
    assert result.ok is False
    assert any(c.name == "context_limit" and not c.ok for c in result.checks)


def test_role_tools_contract_requires_any_overlap():
    role = {"id": "ahman"}
    result = evaluate_role_tools(role, ["memory_search", "bash_exec"], must_have_any=["bash_exec", "tmux_exec"])
    assert result.ok is True


def test_role_tools_contract_fails_when_no_required_tool():
    role = {"id": "ahman"}
    result = evaluate_role_tools(role, ["memory_search"], must_have_any=["bash_exec", "tmux_exec"])
    assert result.ok is False
