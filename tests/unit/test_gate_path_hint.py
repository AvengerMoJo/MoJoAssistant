"""A path the sandbox refuses comes back with the fix, not just the refusal."""
from app.scheduler.safety_policy import SafetyPolicy


def refusal(path):
    return SafetyPolicy().check_tool_execution("read_file", {"danger_level": "low"}, {"path": path})


def test_mistyped_memory_dir_is_named():
    r = refusal("~/memory/roles/cecilia_config.md")
    assert not r["allowed"] and "~/.memory/" in r["reason"] and "with the dot" in r["reason"]


def test_repo_file_points_to_knowledge_get_file():
    r = refusal("./docs/architecture/AGENT_WORKFORCE.md")
    assert not r["allowed"] and "knowledge_get_file" in r["reason"]
