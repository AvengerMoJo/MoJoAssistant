import asyncio
import pytest

from app.scheduler.bash_command import all_read_only, is_no_match, is_read_only, split_commands
from app.scheduler.security_gate import SecurityGate

BASH = {"danger_level": "high"}


@pytest.mark.parametrize("cmd", [
    "ls -la", "grep -rn foo src | head -20", "cat a.txt | wc -l", "find . -name '*.py'",
    "git log --oneline", "git diff HEAD~1", "grep -r 'a;b' . ; echo done", "ls && pwd",
    "rg 'x|y' dir",
])
def test_read_only(cmd):
    assert is_read_only(cmd)


@pytest.mark.parametrize("cmd", [
    "rm x", "ls && rm x", "cat f; rm x", "ls | xargs rm", "cat f > g", "echo a >> g",
    "ls $(rm x)", "ls `rm x`", "find . -delete", "find . -exec rm {} ;", "sed -i s/a/b/ f",
    "git commit -m x", "git push", "FOO=1 ls", "sort -o out in", "python -c 'x'", "curl http://x",
    "", "ls 'unbalanced",
])
def test_not_read_only(cmd):
    assert not is_read_only(cmd)


def test_split_sees_every_command():
    assert [c[0] for c in split_commands("ls && rm x; cat f | wc")] == ["ls", "rm", "cat", "wc"]
    assert "rm" in [c[0] for c in split_commands("ls $(rm x)")]


def test_no_match_is_not_failure():
    assert is_no_match("grep nothing f", 1)
    assert is_no_match("diff a b", 1)
    assert not is_no_match("grep nothing f", 2)
    assert not is_no_match("ls nope", 1)


def _cost(args, n=1):
    g = SecurityGate(default_budget=160)
    g.reset_task("t")
    for _ in range(n):
        g.check("t", "bash_exec", BASH, args)
    return g.task_summary("t")["budget_consumed"]


def test_gate_charges_read_only_one_point():
    assert _cost({"commands": "grep -rn x ."}) == 1
    assert _cost({"commands": ["ls", "cat a | head"]}) == 1
    assert _cost({"command": "ls"}) == 1


def test_gate_charges_writes_full_price():
    assert _cost({"commands": "rm x"}) == 8
    assert _cost({"commands": ["ls", "ls && rm x"]}) == 8
    assert _cost({"commands": "cat f > g"}) == 8


def test_read_only_research_does_not_exhaust_budget():
    assert _cost({"commands": "grep -rn x ."}, n=100) == 100


def _run(commands):
    from app.scheduler.capability_registry import CapabilityRegistry
    reg = CapabilityRegistry.__new__(CapabilityRegistry)
    return asyncio.run(reg._bash_exec({"commands": commands}))


def test_exec_blocks_every_simple_command(tmp_path):
    for cmd in ("ls && rm nothing", "echo hi; rm nothing", "echo hi | xargs true; kill 1"):
        out = _run(cmd)
        assert out["success"] is False and "blocked" in out["error"], cmd


def test_exec_grep_no_match_does_not_abort_batch(tmp_path):
    (tmp_path / "f").write_text("hello\n")
    out = _run([f"grep -c zzz {tmp_path}/f", f"cat {tmp_path}/f"])
    assert out["success"] is True and out["executed"] == 2
