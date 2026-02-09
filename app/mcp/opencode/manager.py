"""
OpenCode Manager

Main orchestrator for OpenCode project lifecycle management.

File: app/mcp/opencode/manager.py
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from app.mcp.opencode.models import ProjectState, ProcessStatus
from app.mcp.opencode.env_manager import EnvManager
from app.mcp.opencode.state_manager import StateManager
from app.mcp.opencode.ssh_manager import SSHManager
from app.mcp.opencode.process_manager import ProcessManager
from app.mcp.opencode.config_manager import ConfigManager


class OpenCodeManager:
    """
    Manages OpenCode server instances and their associated MCP tools.

    Responsibilities:
    - Bootstrap projects (clone repo, start processes)
    - Monitor health
    - Stop/restart projects
    - Track state persistently
    """

    def __init__(self, memory_root: str = None, logger=None):
        self.memory_root = memory_root or os.path.expanduser("~/.memory")
        self.logger = logger
        self.env_manager = EnvManager(self.memory_root)
        self.state_manager = StateManager(self.memory_root)
        self.ssh_manager = SSHManager(self.memory_root)
        self.process_manager = ProcessManager(self.memory_root)
        self.config_manager = ConfigManager(self.memory_root)

        # Check if we're in development mode
        self.is_dev_mode = os.getenv("ENVIRONMENT", "production").lower() in [
            "development",
            "dev",
        ]

        # Load global configuration (fail fast if missing)
        try:
            self.global_config = self.env_manager.read_global_config()
            self._log("Global configuration loaded successfully")
        except (FileNotFoundError, ValueError) as e:
            error_msg = (
                f"Failed to load global configuration:\n\n{str(e)}\n\n"
                f"OpenCode Manager cannot start without global configuration."
            )
            self._log(error_msg, level="error")
            raise RuntimeError(error_msg) from e

    def _log(self, message: str, level: str = "info"):
        """Log message if logger available"""
        if self.logger:
            getattr(self.logger, level)(f"[OpenCode Manager] {message}")

    async def start_project(
        self, project_name: str, git_url: str, user_ssh_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Start or bootstrap an OpenCode project

        Args:
            project_name: Name of the project
            git_url: Git repository URL
            user_ssh_key: Optional user-provided SSH key path

        Returns:
            Dictionary with status and details
        """
        self._log(f"Starting project: {project_name}")

        # Check if project already exists
        existing_project = self.state_manager.get_project(project_name)
        if existing_project:
            # Check if OpenCode is running
            opencode_running = self.process_manager.is_process_running(
                existing_project.opencode.pid
            )

            # Check if global MCP tool is running
            mcp_tool = self.state_manager.get_global_mcp_tool()
            mcp_tool_running = self.process_manager.is_process_running(
                mcp_tool.pid if mcp_tool else None
            )

            if opencode_running and mcp_tool_running:
                self._log(f"Project {project_name} is already running")
                return {
                    "status": "already_running",
                    "project": project_name,
                    "opencode_port": existing_project.opencode.port,
                    "mcp_tool_port": mcp_tool.port if mcp_tool else None,
                    "message": "Project is already running",
                }

            # Restart if stopped/failed
            return await self.restart_project(project_name)

        # Bootstrap new project
        return await self._bootstrap_project(project_name, git_url, user_ssh_key)

    async def _bootstrap_project(
        self, project_name: str, git_url: str, user_ssh_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Bootstrap a new project from scratch"""
        self._log(f"Bootstrapping project: {project_name}")

        try:
            # Step 1: Handle .env configuration (project-specific, no passwords)
            env_path = self.env_manager.get_env_path(project_name)
            info_message = None

            if not self.env_manager.env_exists(project_name):
                self._log(f"Generating project .env for {project_name}")
                env_path, info_message = self.env_manager.generate_env(
                    project_name, git_url, user_ssh_key
                )

            # Step 2: Load and validate configuration (uses global passwords)
            try:
                config = self.env_manager.load_project_config(
                    project_name, self.global_config
                )
            except (FileNotFoundError, ValueError) as e:
                return {"status": "error", "error": "invalid_config", "message": str(e)}

            valid, error = self.env_manager.validate_config(config)
            if not valid:
                return {
                    "status": "error",
                    "error": "invalid_config",
                    "message": error,
                }

            # Step 3: Handle SSH key
            ssh_key_path = config.ssh_key_path
            public_key = None

            if not os.path.exists(ssh_key_path):
                # Generate SSH key
                self._log(f"Generating SSH key for {project_name}")
                (
                    ssh_key_path,
                    public_key_path,
                    public_key,
                ) = self.ssh_manager.generate_key(project_name)

                # Update config with generated key path
                config.ssh_key_path = ssh_key_path

            else:
                # Validate existing key
                valid, error = self.ssh_manager.validate_key(ssh_key_path)
                if not valid:
                    return {
                        "status": "error",
                        "error": "invalid_ssh_key",
                        "message": error,
                    }
                public_key = self.ssh_manager.get_public_key(ssh_key_path)

            # Step 4: Test Git access
            self._log(f"Testing Git access for {project_name}")
            has_access, access_message = self.ssh_manager.test_git_access(
                git_url, ssh_key_path
            )

            if not has_access:
                # Return with instructions to add key
                return {
                    "status": "waiting_for_key",
                    "project": project_name,
                    "message": (
                        "SSH key does not have access to repository yet.\n\n"
                        "Please add this public key to your Git repository:\n\n"
                        f"{public_key}\n\n"
                        f"Public key location: {ssh_key_path}.pub\n\n"
                        "After adding the key, run this command again to retry."
                    ),
                    "public_key": public_key,
                    "public_key_path": f"{ssh_key_path}.pub",
                    "error_detail": access_message,
                }

            # Step 5: Clone repository
            repo_dir = Path(config.sandbox_dir) / "repo"
            if not repo_dir.exists():
                self._log(f"Cloning repository for {project_name}")
                success, clone_message = self.process_manager.clone_repository(
                    git_url, repo_dir, ssh_key_path
                )
                if not success:
                    return {
                        "status": "error",
                        "error": "clone_failed",
                        "message": clone_message,
                    }

            # Step 6: Create .gitignore in sandbox to protect .env
            gitignore_template = (
                Path(__file__).parent / "templates" / ".gitignore.template"
            )
            sandbox_gitignore = Path(config.sandbox_dir) / ".gitignore"
            if gitignore_template.exists() and not sandbox_gitignore.exists():
                import shutil

                shutil.copy(gitignore_template, sandbox_gitignore)
                self._log("Created .gitignore in sandbox to protect secrets")

            # Step 7: Create initial project state
            project_state = ProjectState(
                project_name=project_name,
                sandbox_dir=config.sandbox_dir,
                git_url=git_url,
                ssh_key_path=ssh_key_path,
            )
            self.state_manager.save_project(project_state)

            # Step 8: Start OpenCode server
            self._log(f"Starting OpenCode server for {project_name}")
            opencode_pid, opencode_port, opencode_error = (
                self.process_manager.start_opencode(config, repo_dir)
            )

            if opencode_error:
                self.state_manager.update_process_status(
                    project_name, "opencode", status="failed", error=opencode_error
                )
                return {
                    "status": "error",
                    "error": "opencode_start_failed",
                    "message": opencode_error,
                }

            self.state_manager.update_process_status(
                project_name,
                "opencode",
                pid=opencode_pid,
                port=opencode_port,
                status="starting",
            )

            # Step 9: Health check OpenCode
            self._log(f"Checking OpenCode health for {project_name}")
            healthy, health_message = self.process_manager.check_opencode_health(
                opencode_port, config.opencode_password
            )

            if not healthy:
                self.state_manager.update_process_status(
                    project_name, "opencode", status="failed", error=health_message
                )
                return {
                    "status": "error",
                    "error": "opencode_unhealthy",
                    "message": health_message,
                }

            self.state_manager.update_process_status(
                project_name, "opencode", status="running"
            )

            # Step 10: Add server to global configuration
            self._log(f"Adding {project_name} to global server configuration")
            self.config_manager.add_server(
                project_name=project_name,
                port=opencode_port,
                password=config.opencode_password,
                ssh_key_path=ssh_key_path,
                git_url=git_url,
                sandbox_dir=config.sandbox_dir,
            )

            # Step 11: Ensure global MCP tool is running
            mcp_tool_started = await self._ensure_global_mcp_tool_running()
            if not mcp_tool_started:
                return {
                    "status": "partial",
                    "message": "OpenCode started but global MCP tool failed to start",
                    "opencode_port": opencode_port,
                }

            # Step 12: Increment active project count
            self.state_manager.increment_active_projects()

            # Success!
            self._log(f"Project {project_name} started successfully")

            mcp_tool = self.state_manager.get_global_mcp_tool()
            result = {
                "status": "success",
                "project": project_name,
                "opencode_port": opencode_port,
                "opencode_pid": opencode_pid,
                "mcp_tool_port": mcp_tool.port if mcp_tool else None,
                "sandbox_dir": config.sandbox_dir,
                "message": f"Project {project_name} started successfully",
            }

            if warning_message:
                result["warning"] = warning_message

            return result

        except Exception as e:
            self._log(f"Error bootstrapping project: {str(e)}", "error")
            return {
                "status": "error",
                "error": "bootstrap_failed",
                "message": f"Unexpected error: {str(e)}",
            }

    async def get_status(self, project_name: str) -> Dict[str, Any]:
        """Get project status"""
        project = self.state_manager.get_project(project_name)
        if not project:
            return {
                "status": "not_found",
                "project": project_name,
                "message": f"Project {project_name} not found",
            }

        # Check process health
        opencode_running = self.process_manager.is_process_running(project.opencode.pid)

        # Update status
        if opencode_running:
            self.state_manager.update_process_status(
                project_name, "opencode", status="running"
            )
        else:
            self.state_manager.update_process_status(
                project_name, "opencode", status="stopped"
            )

        self.state_manager.update_health_check(project_name)

        # Reload project state
        project = self.state_manager.get_project(project_name)

        # Get global MCP tool status
        mcp_tool = self.state_manager.get_global_mcp_tool()
        mcp_tool_running = self.process_manager.is_process_running(
            mcp_tool.pid if mcp_tool else None
        )

        return {
            "status": "ok",
            "project": project_name,
            "opencode": {
                "pid": project.opencode.pid,
                "port": project.opencode.port,
                "status": project.opencode.status,
                "running": opencode_running,
            },
            "global_mcp_tool": {
                "pid": mcp_tool.pid if mcp_tool else None,
                "port": mcp_tool.port if mcp_tool else None,
                "status": mcp_tool.status.value if mcp_tool else "not_started",
                "running": mcp_tool_running,
                "active_projects": mcp_tool.active_project_count if mcp_tool else 0,
            },
            "sandbox_dir": project.sandbox_dir,
            "git_url": project.git_url,
            "created_at": project.created_at,
            "last_health_check": project.last_health_check,
        }

    async def stop_project(self, project_name: str) -> Dict[str, Any]:
        """Stop a project"""
        project = self.state_manager.get_project(project_name)
        if not project:
            return {
                "status": "not_found",
                "message": f"Project {project_name} not found",
            }

        self._log(f"Stopping project: {project_name}")

        # Stop OpenCode
        if project.opencode.pid:
            success, error = self.process_manager.stop_process(
                project.opencode.pid, "OpenCode"
            )
            if success:
                self.state_manager.update_process_status(
                    project_name, "opencode", status="stopped"
                )

        # Update server status in configuration
        self.config_manager.update_server_status(project_name, "inactive")

        # Decrement active project count
        self.state_manager.decrement_active_projects()

        # Check if we should stop global MCP tool
        mcp_tool = self.state_manager.get_global_mcp_tool()
        if mcp_tool and mcp_tool.active_project_count == 0:
            self._log("No active projects, stopping global MCP tool")
            await self._stop_global_mcp_tool()

        return {
            "status": "success",
            "project": project_name,
            "message": "Project stopped",
        }

    async def restart_project(self, project_name: str) -> Dict[str, Any]:
        """Restart a project"""
        self._log(f"Restarting project: {project_name}")

        # Get existing project state to reuse ports
        project = self.state_manager.get_project(project_name)
        if not project:
            return {"status": "error", "message": f"Project {project_name} not found"}

        # Check if project was already running before restart
        was_running = (
            project.opencode.status == "running"
            and self.process_manager.is_process_running(project.opencode.pid)
        )

        # Stop OpenCode (but don't stop global MCP tool or change active count)
        if project.opencode.pid:
            success, error = self.process_manager.stop_process(
                project.opencode.pid, "OpenCode"
            )
            if success:
                self.state_manager.update_process_status(
                    project_name, "opencode", status="stopped"
                )

        # Temporarily mark as inactive
        self.config_manager.update_server_status(project_name, "inactive")

        # Get configuration (uses global passwords)
        try:
            config = self.env_manager.load_project_config(
                project_name, self.global_config
            )
        except Exception as e:
            return {"status": "error", "message": f"Failed to load config: {str(e)}"}

        # IMPORTANT: Reuse existing port
        if project.opencode.port:
            config.opencode_port = project.opencode.port
            self._log(f"Reusing OpenCode port: {project.opencode.port}")

        repo_dir = Path(config.sandbox_dir) / "repo"

        # Start OpenCode
        opencode_pid, opencode_port, opencode_error = (
            self.process_manager.start_opencode(config, repo_dir)
        )
        if opencode_error:
            return {"status": "error", "message": opencode_error}

        self.state_manager.update_process_status(
            project_name,
            "opencode",
            pid=opencode_pid,
            port=opencode_port,
            status="starting",
        )

        # Health check OpenCode
        self._log("Checking OpenCode health")
        healthy, health_message = self.process_manager.check_opencode_health(
            opencode_port, config.opencode_password
        )

        if not healthy:
            self.state_manager.update_process_status(
                project_name, "opencode", status="failed", error=health_message
            )
            return {
                "status": "error",
                "error": "opencode_unhealthy",
                "message": health_message,
            }

        self.state_manager.update_process_status(
            project_name, "opencode", status="running"
        )

        # Update server configuration (mark as active, update password if changed)
        self.config_manager.add_server(
            project_name=project_name,
            port=opencode_port,
            password=config.opencode_password,
            ssh_key_path=project.ssh_key_path,
            git_url=project.git_url,
            sandbox_dir=project.sandbox_dir,
        )

        # Increment active_project_count if the project was not running before
        # This handles the case where we restart a project after all projects were stopped
        if not was_running:
            self._log(f"Project was stopped, incrementing active_project_count")
            self.state_manager.increment_active_projects()

        # Ensure global MCP tool is running (will reload config automatically)
        await self._ensure_global_mcp_tool_running()

        # Ensure global MCP tool is running (will reload config automatically)
        await self._ensure_global_mcp_tool_running()

        mcp_tool = self.state_manager.get_global_mcp_tool()

        return {
            "status": "success",
            "project": project_name,
            "message": "Project restarted",
            "opencode_port": opencode_port,
            "mcp_tool_port": mcp_tool.port if mcp_tool else None,
        }

    async def destroy_project(self, project_name: str) -> Dict[str, Any]:
        """Destroy a project (stop + delete sandbox)"""
        self._log(f"Destroying project: {project_name}")

        # Stop first
        await self.stop_project(project_name)

        # Remove from global configuration
        self.config_manager.remove_server(project_name)

        # Get project state
        project = self.state_manager.get_project(project_name)
        if project:
            # Delete sandbox directory
            sandbox_dir = Path(project.sandbox_dir)
            if sandbox_dir.exists():
                import shutil

                shutil.rmtree(sandbox_dir)

            # Delete from state
            self.state_manager.delete_project(project_name)

        return {
            "status": "success",
            "project": project_name,
            "message": "Project destroyed",
        }

    async def list_projects(self) -> Dict[str, Any]:
        """List all projects"""
        projects = self.state_manager.get_all_projects()

        result = {"status": "success", "projects": []}

        for name, project in projects.items():
            opencode_running = self.process_manager.is_process_running(
                project.opencode.pid
            )

            result["projects"].append(
                {
                    "name": name,
                    "opencode_running": opencode_running,
                    "opencode_port": project.opencode.port,
                    "sandbox_dir": project.sandbox_dir,
                }
            )

        # Add global MCP tool info
        mcp_tool = self.state_manager.get_global_mcp_tool()
        if mcp_tool:
            result["global_mcp_tool"] = {
                "pid": mcp_tool.pid,
                "port": mcp_tool.port,
                "status": mcp_tool.status.value,
                "running": self.process_manager.is_process_running(mcp_tool.pid),
                "active_projects": mcp_tool.active_project_count,
            }

        return result

    # ========================================================================
    # Global MCP Tool Lifecycle Helpers (N:1 Architecture)
    # ========================================================================

    async def _ensure_global_mcp_tool_running(self) -> bool:
        """
        Ensure global MCP tool is running, start if needed

        Returns:
            True if running, False if failed to start
        """
        mcp_tool = self.state_manager.get_global_mcp_tool()

        # Check if already running
        if mcp_tool and self.process_manager.is_process_running(mcp_tool.pid):
            self._log("Global MCP tool already running, configuration will auto-reload")

            # If process is running but marked as failed, update status
            if mcp_tool.status == ProcessStatus.FAILED:
                self._log("Updating global MCP tool status from failed to running")
                self.state_manager.update_global_mcp_tool_status(
                    status=ProcessStatus.RUNNING,
                    error=None,
                    last_health_check=datetime.utcnow().isoformat(),
                )

            return True

        # Start global MCP tool
        self._log("Starting global MCP tool")

        # Check for and clean up stale PID file (process killed externally)
        pid_file = Path(self.memory_root) / "global-mcp-tool.pid"
        if pid_file.exists():
            try:
                with open(pid_file, "r") as f:
                    stale_pid = int(f.read().strip())
                if not self.process_manager.is_process_running(stale_pid):
                    self._log(
                        f"Cleaning up stale PID file for dead process (PID {stale_pid})"
                    )
                    pid_file.unlink()
            except Exception as e:
                self._log(f"Error checking stale PID file: {e}", "warning")

        # Get bearer token from environment (fixed global token)
        global_bearer_token = os.getenv(
            "GLOBAL_MCP_BEARER_TOKEN",
            "730d60768d2f6ac0bfd971b2cfb69eba0b3f3bf980745a13b98d3538b996ba6a",  # Fixed token
        )

        servers_config_path = self.config_manager.get_config_path()

        # Determine port (reuse if exists, otherwise use configured default)
        # GLOBAL_MCP_TOOL_PORT allows setting a fixed port (e.g., 3005 for cloudflared)
        default_port = int(os.getenv("GLOBAL_MCP_TOOL_PORT", "3005"))
        port = mcp_tool.port if mcp_tool else default_port

        pid, port, error = self.process_manager.start_global_mcp_tool(
            bearer_token=global_bearer_token,
            servers_config_path=servers_config_path,
            port=port,
        )

        if error:
            self._log(f"Failed to start global MCP tool: {error}", "error")
            self.state_manager.update_global_mcp_tool_status(
                status=ProcessStatus.FAILED,
                error=error,
            )
            return False

        # Update state
        self.state_manager.update_global_mcp_tool_status(
            pid=pid,
            port=port,
            status=ProcessStatus.STARTING,
            started_at=datetime.utcnow().isoformat(),
        )

        # Wait for process to start (not wait for health check)
        self._log("Waiting for global MCP tool to start")
        time.sleep(3)  # Brief wait for process to initialize

        # Check if process is running
        if not self.process_manager.is_process_running(pid):
            self._log(f"Global MCP tool process exited immediately", "error")
            self.state_manager.update_global_mcp_tool_status(
                status=ProcessStatus.FAILED,
                error="Process exited immediately after starting",
            )
            return False

        # Mark as running (health check happens lazily later)
        self.state_manager.update_global_mcp_tool_status(
            status=ProcessStatus.RUNNING,
            last_health_check=datetime.utcnow().isoformat(),
        )

        self._log(f"Global MCP tool started successfully on port {port}")
        return True

    async def _stop_global_mcp_tool(self):
        """Stop global MCP tool"""
        mcp_tool = self.state_manager.get_global_mcp_tool()
        if not mcp_tool or not mcp_tool.pid:
            return

        self._log(f"Stopping global MCP tool (PID {mcp_tool.pid})")
        success, error = self.process_manager.stop_process(
            mcp_tool.pid, "Global MCP tool"
        )

        if success:
            self.state_manager.update_global_mcp_tool_status(
                status=ProcessStatus.STOPPED,
                pid=None,
            )
            self._log("Global MCP tool stopped")
        else:
            self._log(f"Failed to stop global MCP tool: {error}", "error")

    async def get_mcp_status(self) -> Dict[str, Any]:
        """Get global MCP tool status"""
        mcp_tool = self.state_manager.get_global_mcp_tool()

        if not mcp_tool:
            return {
                "status": "not_started",
                "message": "Global MCP tool has never been started",
            }

        running = self.process_manager.is_process_running(mcp_tool.pid)

        # Check for stale state (process killed but PID file remains)
        pid_file = Path(self.memory_root) / "global-mcp-tool.pid"
        if not running and mcp_tool.pid and pid_file.exists():
            self._log(
                f"Process killed externally (PID {mcp_tool.pid}), cleaning up stale state"
            )
            # Remove stale PID file
            try:
                pid_file.unlink()
            except Exception as e:
                self._log(f"Failed to remove stale PID file: {e}", "warning")

            # Update state to stopped
            self.state_manager.update_global_mcp_tool_status(
                status=ProcessStatus.STOPPED,
                pid=None,
            )
            running = False

        return {
            "status": "running" if running else "stopped",
            "pid": mcp_tool.pid,
            "port": mcp_tool.port,
            "active_projects": mcp_tool.active_project_count,
            "started_at": mcp_tool.started_at,
            "last_health_check": mcp_tool.last_health_check,
            "error": mcp_tool.error,
        }

    async def restart_mcp_tool(self) -> Dict[str, Any]:
        """Manually restart global MCP tool"""
        mcp_tool = self.state_manager.get_global_mcp_tool()

        if mcp_tool and mcp_tool.active_project_count == 0:
            return {
                "status": "error",
                "message": "No active projects - MCP tool will not be restarted",
            }

        # Stop if running
        await self._stop_global_mcp_tool()

        # Start again
        success = await self._ensure_global_mcp_tool_running()

        if success:
            mcp_tool = self.state_manager.get_global_mcp_tool()
            return {
                "status": "success",
                "message": "Global MCP tool restarted",
                "pid": mcp_tool.pid,
                "port": mcp_tool.port,
            }
        else:
            return {"status": "error", "message": "Failed to restart global MCP tool"}

    async def get_llm_config(self) -> Dict[str, Any]:
        """Get global OpenCode LLM configuration (providers, models, default model)"""
        import subprocess

        config_path = Path.home() / ".config" / "opencode" / "opencode.json"

        if not config_path.exists():
            return {
                "status": "not_found",
                "message": "OpenCode global config not found",
                "config_path": str(config_path),
            }

        try:
            with open(config_path, "r") as f:
                config = json.load(f)

            current_model = config.get("model", None)

            # Get all available models from opencode CLI (includes built-in providers)
            try:
                result = subprocess.run(
                    ["opencode", "models"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                all_models = [
                    line.strip() for line in result.stdout.splitlines() if line.strip()
                ]
            except Exception:
                all_models = []

            # Group models by provider prefix
            providers_from_models = {}
            for model in all_models:
                parts = model.split("/", 1)
                provider_id = parts[0] if len(parts) > 1 else "unknown"
                if provider_id not in providers_from_models:
                    providers_from_models[provider_id] = []
                providers_from_models[provider_id].append(model)

            return {
                "status": "success",
                "current_model": current_model,
                "available_models": all_models,
                "providers": providers_from_models,
                "config_path": str(config_path),
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to read LLM config: {str(e)}",
            }

    async def set_llm_model(self, model: str) -> Dict[str, Any]:
        """Set the default LLM model for all OpenCode instances"""
        config_path = Path.home() / ".config" / "opencode" / "opencode.json"

        if not config_path.exists():
            return {
                "status": "not_found",
                "message": "OpenCode global config not found",
                "config_path": str(config_path),
            }

        try:
            with open(config_path, "r") as f:
                config = json.load(f)

            old_model = config.get("model", None)
            config["model"] = model

            with open(config_path, "w") as f:
                json.dump(config, f, indent="\t")
                f.write("\n")

            self._log(f"Default model changed: {old_model} -> {model}")

            return {
                "status": "success",
                "previous_model": old_model,
                "current_model": model,
                "message": f"Default model set to {model}",
                "note": "Restart OpenCode sessions to use the new model",
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to set model: {str(e)}",
            }

    async def stop_mcp_tool(self) -> Dict[str, Any]:
        """Manually stop global MCP tool (even with active projects)"""
        mcp_tool = self.state_manager.get_global_mcp_tool()

        if not mcp_tool or not mcp_tool.pid:
            return {
                "status": "error",
                "message": "Global MCP tool is not running",
            }

        # Check if there are active projects
        if mcp_tool.active_project_count > 0:
            self._log(
                f"Stopping global MCP tool with {mcp_tool.active_project_count} active project(s)"
            )
        else:
            self._log("Stopping global MCP tool")

        # Stop the process
        success, error = self.process_manager.stop_process(
            mcp_tool.pid, "Global MCP tool"
        )

        if success:
            self.state_manager.update_global_mcp_tool_status(
                status=ProcessStatus.STOPPED,
                pid=None,
                error=None,
            )
            self._log("Global MCP tool stopped successfully")
            return {
                "status": "success",
                "message": "Global MCP tool stopped",
                "active_projects": mcp_tool.active_project_count,
            }
        else:
            self._log(f"Failed to stop global MCP tool: {error}", "error")
            return {
                "status": "error",
                "message": f"Failed to stop global MCP tool: {error}",
                "active_projects": mcp_tool.active_project_count,
            }
