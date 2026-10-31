"""bash_exec path rules: secrets, writes outside memory, system reads.

The check used to read args["command"] while the tool's parameter is
"commands", so it never fired.  Cases below come from real past commands."""
import pytest

from app.scheduler.safety_policy import SafetyPolicy

P = SafetyPolicy(policy_path="/tmp/__nonexistent_safety_policy__.json")
HIGH = {"danger_level": "high"}


def ok(commands):
    return P.check_tool_execution("bash_exec", HIGH, {"commands": commands})["allowed"]


@pytest.mark.parametrize("cmd", [
    "find /home/alex/Development/Personal/MoJoAssistant -maxdepth 2 -name '*.py'",
    "cat /home/alex/Development/Personal/MoJoAssistant/config/notifications_config.json",
    "grep -rn foo ~/Development/Personal/MoJoAssistant/app | head",
    "cat /etc/os-release", "cat /etc/resolv.conf", "ls /usr/bin | grep chrome",
    "ls ~/.memory/projects/*.json", "cat ~/.memory/scheduler_tasks.json",
    "echo hi > ~/.memory/research/x.md", "echo hi > /tmp/x", "echo hi > out.txt", "ls 2>&1 | head",
    "mkdir -p ~/.memory/tools && cp /home/alex/cella/cella ~/.memory/tools/cella",
    "cat /home/alex/Development/x/.env.example",
    ["ls", "grep -c foo f.txt"],
])
def test_allowed(cmd):
    assert ok(cmd), cmd


@pytest.mark.parametrize("cmd", [
    "cat ~/.ssh/id_rsa", "ls /home/alex/.ssh/", "grep x /home/alex/Development/p/.env",
    "find /home/alex -name id_rsa", "cat ~/.config/ai-credential-manager/vault/x",
    "cat ~/.local/share/opencode/auth.json", "cat ~/.config/opencode/service.json",
    "cat ~/.memory/oauth/clients.json", "cat server.pem",
    "ls && cat ~/.ssh/config",
])
def test_secrets_blocked(cmd):
    assert not ok(cmd), cmd


@pytest.mark.parametrize("cmd", [
    "echo x > ~/.bashrc", "echo x >> /home/alex/.profile", "touch /home/alex/x",
    "cp a ~/.local/bin/a", "sed -i s/a/b/ /home/alex/Development/p/f", "rm -rf /home/alex/Development/p",
    "ls && rm /var/log/syslog", "echo x > ../../escape",
])
def test_writes_outside_memory_blocked(cmd):
    assert not ok(cmd), cmd


@pytest.mark.parametrize("cmd", [
    "cat /etc/passwd", "cat /etc/shadow", "ls /var/log", "ls /root", "find / -name foo",
    "cat /proc/1/environ",
])
def test_system_reads_blocked(cmd):
    assert not ok(cmd), cmd


def test_commands_list_is_checked_not_only_command():
    assert not ok(["ls", "cat ~/.ssh/id_rsa"])
