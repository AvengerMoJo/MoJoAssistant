from app.scheduler.capability_gap_checker import CapabilityGapChecker


def test_explicit_phrase_blocks_without_exec():
    """High-confidence explicit phrases (git clone, npm install, etc.) are still blockers."""
    checker = CapabilityGapChecker()
    result = checker.check(
        goal="git clone https://github.com/example/repo and run npm install",
        resolved_tool_names=["memory_search"],
        role={"id": "ahman"},
    )
    assert result.has_blockers is True


def test_explicit_phrase_allows_with_exec_capability():
    checker = CapabilityGapChecker()
    result = checker.check(
        goal="git clone https://github.com/example/repo and run npm install",
        resolved_tool_names=["bash_exec"],
        role={"id": "ahman"},
    )
    assert result.has_blockers is False


def test_structural_shell_goal_is_warning_not_blocker():
    """Ambiguous structural signals (backtick + pipe) are now WARNING only.
    The LLM classifier in AgenticExecutor handles blocker escalation for these.
    This prevents false positives on technical writing (Python signatures, markdown tables).
    """
    checker = CapabilityGapChecker()
    result = checker.check(
        goal="Run `hostname -I | awk '{print $1}'` and return the first IPv4 address.",
        resolved_tool_names=["memory_search"],
        role={"id": "ahman"},
    )
    assert result.has_blockers is False
    assert result.has_warnings is True  # pipe pattern → warning


def test_structural_shell_goal_no_warning_with_exec():
    checker = CapabilityGapChecker()
    result = checker.check(
        goal="Run `hostname -I | awk '{print $1}'` and return the first IPv4 address.",
        resolved_tool_names=["bash_exec"],
        role={"id": "ahman"},
    )
    assert result.has_blockers is False
    assert result.has_warnings is False


def test_python_signatures_and_table_pipes_are_clean():
    """Legitimate technical writing must never produce a blocker."""
    checker = CapabilityGapChecker()
    result = checker.check(
        goal=(
            "Write a Gist. Table: Technology | Isolation Level | Best For. "
            "Interface: `def can_handle(self, task: TaskConfig) -> bool` "
            "and `async def run(self, task, code: str) -> SandboxResult`."
        ),
        resolved_tool_names=["memory_search", "write_file"],
        role={"id": "anna"},
    )
    assert result.has_blockers is False


def test_playwright_as_proper_noun_reference_is_not_a_blocker():
    """Reproduces a real false positive hit repeatedly in production: a goal
    that mentions "Playwright" as a reference/comparison point (not an
    instruction to use it) used to trigger a browser-capability blocker even
    though no browser automation was actually requested. Same fix pattern as
    the pre-existing "bash_exec" omission above."""
    checker = CapabilityGapChecker()
    result = checker.check(
        goal=(
            "Compare our AI-native browser call approach against traditional "
            "Playwright and Selenium-based automation, grounded in a real "
            "benchmark report."
        ),
        resolved_tool_names=["memory_search", "write_file"],
        role={"id": "paul"},
    )
    assert result.has_blockers is False


def test_playwright_tool_name_still_grants_browser_capability():
    """A real playwright__* tool in the resolved set must still be recognized
    as browser capability (unaffected by removing the literal-phrase blocker)."""
    checker = CapabilityGapChecker()
    result = checker.check(
        goal="Navigate to the page and take a screenshot.",
        resolved_tool_names=["playwright__navigate"],
        role={"id": "paul"},
    )
    assert result.has_blockers is False


def test_behavioral_browser_phrase_without_browser_tool_still_blocks():
    """Genuine behavioral browser instructions (not just a framework name
    mention) must still be caught as blockers when no browser tool is present."""
    checker = CapabilityGapChecker()
    result = checker.check(
        goal="Open browser and navigate to the login page, then take a screenshot.",
        resolved_tool_names=["memory_search"],
        role={"id": "paul"},
    )
    assert result.has_blockers is True
