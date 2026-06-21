"""SandboxBackend plugin interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.sandbox.models import SandboxEntry


class SandboxBackend(ABC):
    """
    Plugin interface for sandbox backends.

    Implement this to add a new execution environment (CubeSandbox, Firecracker,
    Docker, etc.).  ProcessBackend is the built-in bare-process implementation.

    Each method receives the current SandboxEntry and returns an updated copy —
    the caller (SandboxManager) is responsible for persisting it.
    """

    @abstractmethod
    def create(self, entry: SandboxEntry, base_dir: Path) -> SandboxEntry:
        """
        Provision the workspace: clone the repo (or verify it exists).
        Does NOT start any process.  Returns entry with working_dir populated.
        """

    @abstractmethod
    def start(self, entry: SandboxEntry) -> SandboxEntry:
        """
        Start the agent process (or no-op for claude_code).
        Returns entry with pid, port, status="running" on success.
        """

    @abstractmethod
    def stop(self, entry: SandboxEntry) -> SandboxEntry:
        """
        Stop the agent process.  Returns entry with status="stopped".
        """

    @abstractmethod
    def status(self, entry: SandboxEntry) -> SandboxEntry:
        """
        Verify the agent is alive (PID check + HTTP health for opencode).
        Returns entry with current status.
        """

    @abstractmethod
    def destroy(self, entry: SandboxEntry, base_dir: Path) -> None:
        """
        Stop the agent and remove the sandbox directory entirely.
        """
