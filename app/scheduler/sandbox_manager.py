"""
Sandbox Manager — Provision isolated environments for autonomous development.

Supports two modes:
1. Docker Mode — Create containers from base images
2. Tmux Mode — Create tmux sessions with OpenCode

Each sandbox gets:
- Isolated filesystem
- OpenCode server running
- Health monitoring
- Automatic cleanup
"""
# [mojo-integration]

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SandboxConfig:
    """Configuration for a development sandbox."""
    project_name: str
    git_url: Optional[str] = None
    base_dir: Optional[str] = None
    docker_image: str = "ubuntu:22.04"
    opencode_port: int = 4173
    llm_model: str = "qwen/qwen3.5-35b-a3b"
    llm_base_url: str = "http://host.docker.internal:8080/v1"
    mode: str = "docker"  # "docker" or "tmux"


@dataclass
class SandboxState:
    """State of a development sandbox."""
    project_name: str
    mode: str
    status: str  # "creating", "running", "stopped", "error"
    container_id: Optional[str] = None
    tmux_session: Optional[str] = None
    opencode_url: Optional[str] = None
    created_at: Optional[str] = None
    error: Optional[str] = None


class SandboxManager:
    """Manages development sandboxes for autonomous coding."""

    SANDBOX_DIR = Path.home() / ".memory" / "sandboxes"

    def __init__(self, logger=None):
        self.logger = logger
        self.SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
        self._sandboxes: Dict[str, SandboxState] = {}

    def _log(self, msg: str, level: str = "info"):
        if self.logger:
            getattr(self.logger, level)(f"[SandboxManager] {msg}")

    def create_sandbox(self, config: SandboxConfig) -> SandboxState:
        """Create a new development sandbox."""
        state = SandboxState(
            project_name=config.project_name,
            mode=config.mode,
            status="creating",
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        try:
            if config.mode == "docker":
                self._create_docker_sandbox(config, state)
            elif config.mode == "tmux":
                self._create_tmux_sandbox(config, state)
            else:
                raise ValueError(f"Unknown sandbox mode: {config.mode}")

            state.status = "running"
            self._sandboxes[config.project_name] = state
            self._save_state(config.project_name, state)
            self._log(f"Sandbox created for {config.project_name} ({config.mode})")
            return state

        except Exception as e:
            state.status = "error"
            state.error = str(e)
            self._log(f"Failed to create sandbox: {e}", "error")
            return state

    def _create_docker_sandbox(self, config: SandboxConfig, state: SandboxState):
        """Create a Docker container for development."""
        container_name = f"mojo-{config.project_name}"

        # Check if container exists
        result = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True, text=True
        )

        if result.returncode == 0:
            # Container exists, start it
            subprocess.run(["docker", "start", container_name], check=True)
            state.container_id = container_name
        else:
            # Create new container
            cmd = [
                "docker", "run", "-d",
                "--name", container_name,
                "-p", f"{config.opencode_port}:4173",
                "-v", f"{config.base_dir or os.getcwd()}:/workspace",
                config.docker_image,
                "sleep", "infinity"
            ]
            subprocess.run(cmd, check=True)
            state.container_id = container_name

        state.opencode_url = f"http://localhost:{config.opencode_port}"

    def _create_tmux_sandbox(self, config: SandboxConfig, state: SandboxState):
        """Create a tmux session for development."""
        session_name = f"mojo-{config.project_name}"

        # Create tmux session
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session_name],
            check=True
        )
        state.tmux_session = session_name

        # Start OpenCode in the session
        if config.base_dir:
            subprocess.run(
                ["tmux", "send-keys", "-t", session_name,
                 f"cd {config.base_dir} && opencode", "Enter"],
                check=True
            )
        else:
            subprocess.run(
                ["tmux", "send-keys", "-t", session_name, "opencode", "Enter"],
                check=True
            )

        state.opencode_url = f"http://localhost:{config.opencode_port}"

    def stop_sandbox(self, project_name: str) -> bool:
        """Stop a development sandbox."""
        state = self._sandboxes.get(project_name)
        if not state:
            return False

        try:
            if state.mode == "docker" and state.container_id:
                subprocess.run(["docker", "stop", state.container_id], check=True)
            elif state.mode == "tmux" and state.tmux_session:
                subprocess.run(["tmux", "kill-session", "-t", state.tmux_session], check=True)

            state.status = "stopped"
            self._save_state(project_name, state)
            self._log(f"Sandbox stopped for {project_name}")
            return True

        except Exception as e:
            self._log(f"Failed to stop sandbox: {e}", "error")
            return False

    def destroy_sandbox(self, project_name: str) -> bool:
        """Destroy a development sandbox completely."""
        state = self._sandboxes.get(project_name)
        if not state:
            return False

        try:
            if state.mode == "docker" and state.container_id:
                subprocess.run(["docker", "rm", "-f", state.container_id], check=True)
            elif state.mode == "tmux" and state.tmux_session:
                subprocess.run(["tmux", "kill-session", "-t", state.tmux_session], check=True)

            # Remove state file
            state_file = self.SANDBOX_DIR / f"{project_name}.json"
            if state_file.exists():
                state_file.unlink()

            self._sandboxes.pop(project_name, None)
            self._log(f"Sandbox destroyed for {project_name}")
            return True

        except Exception as e:
            self._log(f"Failed to destroy sandbox: {e}", "error")
            return False

    def get_status(self, project_name: str) -> Optional[SandboxState]:
        """Get the status of a sandbox."""
        return self._sandboxes.get(project_name)

    def list_sandboxes(self) -> List[SandboxState]:
        """List all sandboxes."""
        return list(self._sandboxes.values())

    def _save_state(self, project_name: str, state: SandboxState):
        """Save sandbox state to file."""
        state_file = self.SANDBOX_DIR / f"{project_name}.json"
        with open(state_file, "w") as f:
            json.dump({
                "project_name": state.project_name,
                "mode": state.mode,
                "status": state.status,
                "container_id": state.container_id,
                "tmux_session": state.tmux_session,
                "opencode_url": state.opencode_url,
                "created_at": state.created_at,
                "error": state.error,
            }, f, indent=2)

    def _load_states(self):
        """Load all sandbox states from files."""
        for state_file in self.SANDBOX_DIR.glob("*.json"):
            try:
                with open(state_file) as f:
                    data = json.load(f)
                state = SandboxState(**data)
                self._sandboxes[state.project_name] = state
            except Exception as e:
                self._log(f"Failed to load state from {state_file}: {e}", "warning")
