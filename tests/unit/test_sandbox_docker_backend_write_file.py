"""
Regression test: DockerSandboxBackend.write_file() used tempfile.NamedTemporaryFile
without importing the tempfile module, so every call raised NameError. Found live
2026-07-30 when Paul (role) hit it mid-task via the write_file tool.
"""

from unittest.mock import MagicMock, patch

from app.scheduler.sandbox.docker_backend import DockerSandboxBackend
from app.scheduler.sandbox.base import SandboxHandle


def test_write_file_does_not_raise_nameerror():
    backend = DockerSandboxBackend()
    handle = SandboxHandle(
        task_id="t1", sandbox_id="fake-container-id", backend="docker", working_dir="/workspace"
    )

    with patch.object(backend, "exec", return_value={"success": True, "stdout": "", "stderr": ""}), \
         patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")), \
         patch("os.unlink"):
        # Must not raise NameError: name 'tempfile' is not defined
        backend.write_file(handle, "/workspace/repo/README.md", "hello world")
