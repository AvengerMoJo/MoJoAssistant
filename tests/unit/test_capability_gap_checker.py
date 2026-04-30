from app.scheduler.capability_gap_checker import CapabilityGapChecker


def test_shell_style_goal_blocks_without_exec_or_terminal():
    checker = CapabilityGapChecker()
    result = checker.check(
        goal="Run `hostname -I | awk '{print $1}'` and return the first IPv4 address.",
        resolved_tool_names=["memory_search"],
        role={"id": "ahman"},
    )
    assert result.has_blockers is True
    assert any("shell-command syntax" in b for b in result.blockers)


def test_shell_style_goal_allows_with_exec_capability():
    checker = CapabilityGapChecker()
    result = checker.check(
        goal="Run `hostname -I | awk '{print $1}'` and return the first IPv4 address.",
        resolved_tool_names=["bash_exec"],
        role={"id": "ahman"},
    )
    assert result.has_blockers is False
