"""Unit tests for the SSH remote-host sandbox backend.

All ssh invocations are mocked via subprocess.run — no network, no remote
host. Tests assert on the exact remote command strings so quoting bugs
(tilde expansion, password-on-command-line, injection via sandbox_id) are
caught at the unit level.
"""

from __future__ import annotations

import shlex
from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    p = tmp_path / "sandbox_sessions.json"
    monkeypatch.setenv("SANDBOX_SESSION_STORE", str(p))
    yield p


def _proc(rc=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


class FakeSSH:
    """Routes subprocess.run ssh calls.

    A matcher may be a substring or a callable. A callable matcher returns
    False (no match), True (use the paired result), or a SimpleNamespace
    result directly (lets tests vary output across successive calls).
    """

    def __init__(self):
        self.calls = []    # full argv lists, in order
        self.kwargs = []   # subprocess kwargs aligned with calls
        self.routes = []   # (matcher, result)

    def on(self, matcher, rc=0, stdout="", stderr=""):
        self.routes.append((matcher, _proc(rc=rc, stdout=stdout, stderr=stderr)))

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        self.kwargs.append(kwargs)
        remote = cmd[-1]
        for matcher, result in self.routes:
            if callable(matcher):
                verdict = matcher(remote)
                if verdict is True:
                    return result
                if verdict:
                    return verdict
            elif matcher in remote:
                return result
        return _proc(rc=1, stderr=f"no fake route for: {remote!r}")


def _backend(**kw):
    from app.scheduler.sandbox.ssh_backend import SSHRemoteBackend
    defaults = dict(host="remote-host", user="deploy", url_host="remote-host")
    defaults.update(kw)
    return SSHRemoteBackend(**defaults)


def _spawn_routes(fake, pid="4242", used_ports=""):
    """Routes for everything after opencode detection: dirs, port, env, spawn."""
    fake.on(lambda r: "mkdir -p" in r)
    fake.on(lambda r: "ss -ltn" in r, stdout=used_ports)
    fake.on(lambda r: "cat >" in r)
    fake.on(lambda r: "serve" in r and "echo $!" in r, stdout=f"{pid}\n")


def _detect_route(fake, outputs):
    """Detection probe returning successive outputs (first missing, then found)."""
    seq = iter(outputs)

    def matcher(remote):
        if "command -v opencode" not in remote:
            return False
        try:
            return _proc(stdout=next(seq))
        except StopIteration:
            return _proc(rc=1, stderr="detection probe exhausted")

    fake.on(matcher)


# ----------------------------------------------------------------------
# config guard
# ----------------------------------------------------------------------


def test_unconfigured_host_raises_with_config_hint():
    from app.scheduler.sandbox.ssh_backend import SSHRemoteBackend

    backend = SSHRemoteBackend()
    with pytest.raises(RuntimeError, match="backends.ssh.host"):
        backend.start("t1", "")


# ----------------------------------------------------------------------
# start()
# ----------------------------------------------------------------------


def test_start_installs_opencode_and_spawns_serve():
    fake = FakeSSH()
    # First detection: not installed. Second (post-install): found.
    _detect_route(fake, ["", "/home/deploy/.bun/bin/opencode\n"])
    fake.on(lambda r: "bun install -g opencode-ai" in r, stdout="OK\n")
    _spawn_routes(fake, pid="4242", used_ports="4600\n")

    backend = _backend()
    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake), \
         patch.object(backend, "_wait_healthy", return_value=True):
        handle = backend.start("taskA", "~/projects/bizbuild")

    assert handle.url == "http://remote-host:4601"  # 4600 taken in ss output
    assert handle.sandbox_id == "4242"
    assert handle.state == "running"
    assert handle.backend == "ssh"
    assert handle.working_dir == "~/projects/bizbuild"
    assert handle.password  # random per-task password

    remote_cmds = [c[-1] for c in fake.calls]
    assert any("bun install -g opencode-ai" in r for r in remote_cmds)

    spawn_cmd = next(r for r in remote_cmds if "serve" in r and "echo $!" in r)
    # Password must come from the env file, never the command line.
    assert handle.password not in spawn_cmd
    assert "OPENCODE_SERVER_PASSWORD" not in spawn_cmd
    assert ". \"$HOME\"/.mojo/task_logs/taskA/env" in spawn_cmd
    assert "--hostname 0.0.0.0" in spawn_cmd
    # Tilde working dir must keep expanding on the remote.
    assert 'cd "$HOME"/' in spawn_cmd
    # & binds only to the launch (brace group), not the whole setup chain —
    # otherwise the async subshell blocks on opencode and ssh never returns.
    assert "< /dev/null & } ; echo $!" in spawn_cmd

    # Persisted
    from app.scheduler.sandbox.base import load_handle
    assert load_handle("taskA").sandbox_id == "4242"


def test_start_fails_loud_when_install_disabled_and_missing():
    fake = FakeSSH()
    _detect_route(fake, [""])

    backend = _backend(install_opencode=False)
    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        with pytest.raises(RuntimeError, match="install_opencode"):
            backend.start("taskB", "")


def test_start_falls_back_to_curl_installer_when_no_bun():
    fake = FakeSSH()
    _detect_route(fake, ["", "/home/deploy/.opencode/bin/opencode\n"])
    fake.on(lambda r: "bun install -g opencode-ai" in r, rc=1,
            stderr="bun: command not found")
    fake.on(lambda r: "opencode.ai/install" in r, stdout="OK\n")
    _spawn_routes(fake, pid="1\n")

    backend = _backend()
    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake), \
         patch.object(backend, "_wait_healthy", return_value=True):
        handle = backend.start("taskF", "")

    remote_cmds = [c[-1] for c in fake.calls]
    assert any("curl -fsSL https://opencode.ai/install | bash" in r for r in remote_cmds)
    assert handle.sandbox_id == "1"


def test_start_resumes_alive_remote_pid_without_respawn():
    from app.scheduler.sandbox.base import SandboxHandle, store_handle

    stored = SandboxHandle(
        task_id="taskC", backend="ssh", sandbox_id="5555",
        url="http://remote-host:4600", state="paused",
        working_dir="~/proj",
    )
    store_handle(stored)

    fake = FakeSSH()
    fake.on(lambda r: "kill -0 5555" in r, stdout="alive\n")
    fake.on(lambda r: "kill -CONT 5555" in r)

    backend = _backend()
    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        handle = backend.start("taskC", "~/proj")

    assert handle.sandbox_id == "5555"
    assert handle.state == "running"
    remote_cmds = [c[-1] for c in fake.calls]
    assert any("kill -CONT 5555" in r for r in remote_cmds)
    assert not any("serve" in r and "echo $!" in r for r in remote_cmds)


def test_start_ignores_handles_from_other_backends():
    from app.scheduler.sandbox.base import SandboxHandle, store_handle

    store_handle(SandboxHandle(
        task_id="taskD", backend="host", sandbox_id="9999", state="running",
    ))
    # Host pid 9999 is not ours to touch; backend must not probe/kill it.
    fake = FakeSSH()
    _detect_route(fake, ["/home/deploy/.bun/bin/opencode\n"])
    _spawn_routes(fake, pid="777")

    backend = _backend()
    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake), \
         patch.object(backend, "_wait_healthy", return_value=True):
        handle = backend.start("taskD", "")

    assert handle.sandbox_id == "777"
    remote_cmds = [c[-1] for c in fake.calls]
    assert not any("kill -0 9999" in r for r in remote_cmds)


def test_start_health_failure_kills_remote_and_mentions_tailnet():
    fake = FakeSSH()
    _detect_route(fake, ["/home/deploy/.bun/bin/opencode\n"])
    _spawn_routes(fake, pid="31337")
    fake.on(lambda r: "tail -n 30" in r, stdout="opencode: boom\n")
    fake.on(lambda r: "kill 31337" in r)

    backend = _backend(boot_timeout=0)
    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        with pytest.raises(RuntimeError, match="tailnet") as excinfo:
            backend.start("taskE", "")

    remote_cmds = [c[-1] for c in fake.calls]
    assert any("kill 31337" in r for r in remote_cmds)
    assert "boom" in str(excinfo.value)  # remote log tail surfaced in the error


def test_start_default_working_dir_uses_task_id():
    fake = FakeSSH()
    _detect_route(fake, ["/home/deploy/.bun/bin/opencode\n"])
    _spawn_routes(fake, pid="5")

    backend = _backend()
    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake), \
         patch.object(backend, "_wait_healthy", return_value=True):
        handle = backend.start("task/id spaces", "")

    assert handle.working_dir == "~/.mojo/sandboxes/task_id_spaces"
    remote_cmds = [c[-1] for c in fake.calls]
    assert any(".mojo/sandboxes/task_id_spaces" in r for r in remote_cmds)


# ----------------------------------------------------------------------
# pause / resume / kill
# ----------------------------------------------------------------------


def test_pause_resume_use_remote_sigstop_sigcont():
    from app.scheduler.sandbox.base import SandboxHandle

    backend = _backend()
    handle = SandboxHandle(
        task_id="tP", backend="ssh", sandbox_id="4321", state="running",
    )

    fake = FakeSSH()
    fake.on(lambda r: "kill -0 4321" in r, stdout="alive\n")
    fake.on(lambda r: "kill -STOP 4321" in r)
    fake.on(lambda r: "kill -CONT 4321" in r)

    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        paused = backend.pause(handle)
        assert paused.state == "paused"
        resumed = backend.resume(handle)
        assert resumed.state == "running"


def test_resume_raises_when_remote_pid_gone():
    from app.scheduler.sandbox.base import SandboxHandle

    backend = _backend()
    handle = SandboxHandle(
        task_id="tG", backend="ssh", sandbox_id="1111", state="paused",
    )
    fake = FakeSSH()
    fake.on(lambda r: "kill -0 1111" in r, rc=1)  # dead

    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        with pytest.raises(RuntimeError, match="cannot resume"):
            backend.resume(handle)


def test_kill_terms_kills_and_deletes_handle():
    from app.scheduler.sandbox.base import SandboxHandle, store_handle, load_handle

    backend = _backend()
    handle = SandboxHandle(
        task_id="tK", backend="ssh", sandbox_id="2222", state="paused",
    )
    store_handle(handle)

    fake = FakeSSH()
    fake.on(lambda r: "kill 2222" in r)

    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        backend.kill(handle)

    remote_cmds = [c[-1] for c in fake.calls]
    assert any("kill 2222" in r and "kill -9 2222" in r for r in remote_cmds)
    assert load_handle("tK") is None


def test_kill_sanitizes_corrupt_sandbox_id():
    from app.scheduler.sandbox.base import SandboxHandle, store_handle

    backend = _backend()
    handle = SandboxHandle(
        task_id="tX", backend="ssh", sandbox_id="'; rm -rf /; '",
        state="running",
    )
    store_handle(handle)

    fake = FakeSSH()
    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        backend.kill(handle)  # must not raise, must not ssh anything

    assert fake.calls == []


# ----------------------------------------------------------------------
# health / logs
# ----------------------------------------------------------------------


def test_health_check_ok():
    from app.scheduler.sandbox.base import SandboxHandle

    backend = _backend()
    handle = SandboxHandle(
        task_id="tH", backend="ssh", sandbox_id="1", state="running",
        url="http://remote-host:4600", password="pw",
    )
    fake_resp = SimpleNamespace(status_code=200)
    with patch("httpx.get", return_value=fake_resp) as hg:
        result = backend.health_check(handle)
    assert result["status"] == "ok"
    assert hg.call_args.kwargs.get("auth") == ("opencode", "pw")


def test_health_check_error_on_connection_failure():
    from app.scheduler.sandbox.base import SandboxHandle

    backend = _backend()
    handle = SandboxHandle(
        task_id="tH2", backend="ssh", sandbox_id="1", state="running",
        url="http://remote-host:4600",
    )
    with patch("httpx.get", side_effect=OSError("unreachable")):
        result = backend.health_check(handle)
    assert result["status"] == "error"


def test_get_log_path_mirrors_remote_log_locally(tmp_path):
    from app.scheduler.sandbox.base import SandboxHandle

    backend = _backend()
    handle = SandboxHandle(
        task_id="tL", backend="ssh", sandbox_id="1", state="running",
        log_path=str(tmp_path / "remote_agent.log"),
    )
    fake = FakeSSH()
    fake.on(lambda r: "tail -c 200000" in r, stdout="line1\nline2\n")

    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        path = backend.get_log_path(handle)

    assert path == tmp_path / "remote_agent.log"
    assert path.read_text() == "line1\nline2\n"


# ----------------------------------------------------------------------
# exec / files
# ----------------------------------------------------------------------


def test_exec_cds_to_workdir_and_quotes_command():
    from app.scheduler.sandbox.base import SandboxHandle

    backend = _backend()
    handle = SandboxHandle(
        task_id="tE", backend="ssh", sandbox_id="1", state="running",
        working_dir="~/proj",
    )
    fake = FakeSSH()
    fake.on(lambda r: "bash -c" in r, stdout="done\n")

    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        result = backend.exec(handle, "echo 'hi there'; ls")

    assert result["success"] is True
    assert result["stdout"] == "done\n"
    remote = fake.calls[0][-1]
    assert remote.startswith('cd "$HOME"/')
    assert f"bash -c {shlex.quote('echo ' + chr(39) + 'hi there' + chr(39) + '; ls')}" in remote


def test_write_file_streams_content_over_stdin():
    from app.scheduler.sandbox.base import SandboxHandle

    backend = _backend()
    handle = SandboxHandle(task_id="tW", backend="ssh", sandbox_id="1", state="running")

    fake = FakeSSH()
    fake.on(lambda r: "cat >" in r)

    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake) as run:
        backend.write_file(handle, "~/proj/a b.txt", "hello world")

    remote = fake.calls[0][-1]
    assert "cat > " in remote
    assert 'mkdir -p "$HOME"/' in remote
    assert fake.kwargs[0].get("input") == "hello world"


def test_write_file_content_never_in_command_line():
    from app.scheduler.sandbox.base import SandboxHandle

    backend = _backend()
    handle = SandboxHandle(task_id="tW2", backend="ssh", sandbox_id="1", state="running")
    secret = "PRIVATE_KEY_DATA'; rm -rf /; echo '"
    fake = FakeSSH()
    fake.on(lambda r: "cat >" in r)

    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake) as run:
        backend.write_file(handle, "~/proj/secret", secret)

    remote = fake.calls[0][-1]
    assert secret not in remote
    assert fake.kwargs[0].get("input") == secret


def test_read_file_and_list_files():
    from app.scheduler.sandbox.base import SandboxHandle

    backend = _backend()
    handle = SandboxHandle(task_id="tR", backend="ssh", sandbox_id="1", state="running")
    fake = FakeSSH()
    fake.on(lambda r: r.startswith("cat "), stdout="file body\n")
    fake.on(lambda r: r.startswith("ls -1 "), stdout="a.py\nb.py\n")

    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        assert backend.read_file(handle, "~/proj/a.py") == "file body\n"
        assert backend.list_files(handle, "~/proj") == ["a.py", "b.py"]


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def test_rp_keeps_tilde_expansion():
    from app.scheduler.sandbox.ssh_backend import _rp

    assert _rp("~") == '"$HOME"'
    assert _rp("~/.mojo/x") == '"$HOME"/' + shlex.quote(".mojo/x")
    assert _rp('"; rm -rf /') == shlex.quote('"; rm -rf /')
    assert _rp("/plain/path") == shlex.quote("/plain/path")


def test_safe_id_strips_path_characters():
    from app.scheduler.sandbox.ssh_backend import _safe_id

    assert _safe_id("cs-abc_123") == "cs-abc_123"
    assert _safe_id("task/with/slashes spaces") == "task_with_slashes_spaces"


def test_detection_command_forces_zero_exit():
    """Live bug 2026-09-14: absent opencode made the last probe exit 1 and
    _run_remote_checked raised instead of falling through to install."""
    backend = _backend()
    fake = FakeSSH()
    # Remote shell exits 0 thanks to the trailing "; true"; stdout empty.
    fake.on(lambda r: "command -v opencode" in r, rc=0, stdout="")

    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        assert backend._detect_opencode_bin() == ""

    sent = fake.calls[0][-1]
    assert sent.rstrip().endswith("; true")


def test_remote_free_port_picks_first_free():
    backend = _backend(port_range=[4600, 4602])
    fake = FakeSSH()
    fake.on(lambda r: "ss -ltn" in r,
            stdout="22\n4600\n4601\n")  # pipeline output: bare ports
    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        assert backend._remote_free_port() == 4602


def test_remote_free_port_falls_back_when_ss_missing():
    backend = _backend()
    fake = FakeSSH()
    fake.on(lambda r: "ss -ltn" in r, rc=1, stderr="ss: command not found")
    with patch("app.scheduler.sandbox.ssh_backend.subprocess.run", fake):
        assert backend._remote_free_port() == 4600


def test_ssh_base_includes_batchmode_and_identity():
    backend = _backend(identity_file="~/.ssh/id_ed25519", ssh_port=2222)
    base = backend._ssh_base()
    assert base[0] == "ssh"
    assert "BatchMode=yes" in base
    assert "accept-new" in " ".join(base)
    assert "2222" in base
    assert any(str(p).endswith("id_ed25519") for p in base if isinstance(p, str))
    assert base[-1] == "deploy@remote-host"
