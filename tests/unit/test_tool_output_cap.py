from app.scheduler.agentic_executor import _cap_tool_output


def test_shell_and_file_tools_keep_the_small_cap():
    out = _cap_tool_output("bash_exec", "x" * 5000)
    assert len(out) < 4200 and "truncated 1000 chars" in out


def test_other_tools_get_a_large_cap_so_one_result_cannot_blow_the_context():
    out = _cap_tool_output("playwright__browser_evaluate", "x" * 1_500_000)
    assert out.startswith("x" * 100_000) and "truncated 1400000 chars" in out
    assert len(out) < 100_100


def test_results_under_the_cap_are_untouched():
    assert _cap_tool_output("playwright__browser_evaluate", "x" * 135) == "x" * 135
