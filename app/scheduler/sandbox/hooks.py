"""
Sandbox lifecycle hooks — pluggable pre/post setup steps.

A "hook" is a small, named, config-driven unit of work that runs at a
specific point in a sandbox's lifecycle. This replaces hardcoded assumptions
(e.g. "every sandbox clone is a bare `git clone <url>` with whatever auth
happens to be on the host") with a pluggable list the user can select from
or extend via config — no code change required to add a new prepare
strategy for a new project.

Why this exists: the mcp-buffer incident (2026-07-06) showed the sandbox
system had exactly one hardcoded clone strategy. A public HTTPS repo and a
private SSH-only repo need different setup, and the OpenCode coding-agent
path additionally auto-generates SSH deploy keys that need a human step —
none of that was ever a choice, it was the only path. Hooks make it a choice.

Lifecycle points:
  pre_prepare — runs once, right after a sandbox/container is up but before
                it's handed to a task. Typical use: clone a repo, checkout a
                branch, install dependencies, inject env vars.
  post_task   — runs after a task using the sandbox finishes (success or
                failure). Typical use: upload artifacts, scrub credentials,
                extra teardown beyond the backend's own kill/pause.

Hook registry: ~/.memory/config/sandbox_hooks.json
{
  "hooks": {
    "my_custom_hook": {"type": "shell", "command": "~/.memory/hooks/my_hook.sh"}
  }
}
Built-in hooks (git_clone_default, git_clone_public_https,
git_clone_ssh_existing_key, noop) are always available by name without
needing a config entry — the config file is only for registering NEW
(shell-backed or future python-backed) hooks, same pattern as
capability_catalog.json's tool_registry executor types.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_HOOKS_CONFIG_PATH = Path.home() / ".memory" / "config" / "sandbox_hooks.json"


@dataclass
class HookContext:
    """Everything a hook might need. Not every field is set at every point."""
    point: str                      # "pre_prepare" | "post_task"
    git_url: Optional[str] = None
    working_dir: Optional[str] = None
    repo: Optional[str] = None      # short project_registry key, if known
    exec_fn: Optional[Callable[[str, int], Awaitable[Dict[str, Any]]]] = None
    # exec_fn(command, timeout_s) -> {"success": bool, "stdout": str, "stderr": str}
    # runs the command inside the sandbox this hook is preparing.
    params: Dict[str, Any] = field(default_factory=dict)  # hook-specific extras
    task_result: Optional[Dict[str, Any]] = None  # set at post_task


@dataclass
class HookResult:
    success: bool
    message: str = ""
    working_dir: Optional[str] = None  # pre_prepare hooks may report where code landed
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success, "message": self.message,
            "working_dir": self.working_dir, "data": self.data,
        }


# ---------------------------------------------------------------------------
# Built-in hooks
# ---------------------------------------------------------------------------

async def _hook_noop(ctx: HookContext) -> HookResult:
    return HookResult(success=True, message="noop hook — no setup performed")


async def _hook_git_clone_default(ctx: HookContext) -> HookResult:
    """Bare `git clone <url>` — whatever auth is already on the host/container.

    This is the original, always-worked-until-it-didn't behavior. Kept as the
    default for backward compatibility; prefer a more specific hook below
    once you know whether the repo is public or private.
    """
    if not ctx.git_url or not ctx.exec_fn:
        return HookResult(success=False, message="git_clone_default requires git_url and an exec_fn")
    clone_dir = ctx.params.get("clone_dir", "/workspace/repo")
    result = await ctx.exec_fn(f"git clone {ctx.git_url} {clone_dir}", 180)
    if result.get("success"):
        return HookResult(success=True, message=f"cloned {ctx.git_url}", working_dir=clone_dir)
    return HookResult(success=False, message=f"git clone failed: {result.get('stderr', '')}")


async def _hook_git_clone_public_https(ctx: HookContext) -> HookResult:
    """Clone a public repo over HTTPS — no credentials needed or used.

    Use this for any repo that doesn't require authentication. Avoids the
    SSH-deploy-key dance entirely, which is the right choice whenever it's
    available — least privilege, zero credential management.
    """
    if not ctx.git_url:
        return HookResult(success=False, message="git_clone_public_https requires git_url")
    if not ctx.exec_fn:
        return HookResult(success=False, message="git_clone_public_https requires an exec_fn")
    https_url = ctx.git_url
    if https_url.startswith("git@github.com:"):
        https_url = "https://github.com/" + https_url[len("git@github.com:"):].removesuffix(".git")
    clone_dir = ctx.params.get("clone_dir", "/workspace/repo")
    result = await ctx.exec_fn(f"git clone --depth 1 {https_url} {clone_dir}", 180)
    if result.get("success"):
        return HookResult(success=True, message=f"cloned {https_url} (public, no auth)", working_dir=clone_dir)
    return HookResult(success=False, message=f"public HTTPS clone failed: {result.get('stderr', '')}")


async def _hook_git_clone_ssh_existing_key(ctx: HookContext) -> HookResult:
    """Clone via SSH using an already-provisioned key — never auto-generates one.

    params: ssh_key_path (required)
    Use for private repos where a deploy key already exists (see
    opencode-mcp-tool-servers.json entries for examples). Fails loudly if the
    key is missing rather than silently falling back to key generation.
    """
    ssh_key_path = ctx.params.get("ssh_key_path")
    if not ssh_key_path or not Path(ssh_key_path).expanduser().exists():
        return HookResult(
            success=False,
            message=f"ssh_key_path {ssh_key_path!r} not provided or does not exist — "
                    "this hook never auto-generates keys, provide an existing one",
        )
    if not ctx.git_url or not ctx.exec_fn:
        return HookResult(success=False, message="git_clone_ssh_existing_key requires git_url and an exec_fn")
    clone_dir = ctx.params.get("clone_dir", "/workspace/repo")
    ssh_cmd = f"GIT_SSH_COMMAND='ssh -i {ssh_key_path} -o StrictHostKeyChecking=no'"
    result = await ctx.exec_fn(f"{ssh_cmd} git clone {ctx.git_url} {clone_dir}", 180)
    if result.get("success"):
        return HookResult(success=True, message=f"cloned {ctx.git_url} via {ssh_key_path}", working_dir=clone_dir)
    return HookResult(success=False, message=f"SSH clone failed: {result.get('stderr', '')}")


_BUILTIN_HOOKS: Dict[str, Callable[[HookContext], Awaitable[HookResult]]] = {
    "noop": _hook_noop,
    "git_clone_default": _hook_git_clone_default,
    "git_clone_public_https": _hook_git_clone_public_https,
    "git_clone_ssh_existing_key": _hook_git_clone_ssh_existing_key,
}


def list_hooks() -> Dict[str, Any]:
    """List built-in hooks plus any user-registered ones from config."""
    result = {name: {"type": "builtin"} for name in _BUILTIN_HOOKS}
    cfg = _load_config()
    for name, entry in cfg.get("hooks", {}).items():
        result[name] = entry
    return result


def _load_config() -> Dict[str, Any]:
    if not _HOOKS_CONFIG_PATH.exists():
        return {"hooks": {}}
    try:
        return json.loads(_HOOKS_CONFIG_PATH.read_text())
    except Exception as e:
        logger.warning("sandbox_hooks: failed to load %s: %s", _HOOKS_CONFIG_PATH, e)
        return {"hooks": {}}


async def _run_shell_hook(command: str, ctx: HookContext) -> HookResult:
    """Run a user-defined shell script hook. The script receives context as
    JSON on stdin and must print a JSON object {success, message, working_dir?,
    data?} on stdout.
    """
    payload = json.dumps({
        "point": ctx.point, "git_url": ctx.git_url, "working_dir": ctx.working_dir,
        "repo": ctx.repo, "params": ctx.params, "task_result": ctx.task_result,
    })
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(payload.encode()), timeout=180
        )
        if proc.returncode != 0:
            return HookResult(success=False, message=f"shell hook exited {proc.returncode}: {stderr.decode()[:500]}")
        parsed = json.loads(stdout.decode())
        return HookResult(
            success=bool(parsed.get("success")),
            message=parsed.get("message", ""),
            working_dir=parsed.get("working_dir"),
            data=parsed.get("data", {}),
        )
    except Exception as e:
        return HookResult(success=False, message=f"shell hook failed: {e}")


async def run_hook(hook_name: str, ctx: HookContext) -> HookResult:
    """Run a named hook. Unknown hook names fail loudly rather than silently
    no-op'ing — a typo in a hook name should never look like success.
    """
    if hook_name in _BUILTIN_HOOKS:
        try:
            return await _BUILTIN_HOOKS[hook_name](ctx)
        except Exception as e:
            logger.warning("sandbox_hooks: hook '%s' raised: %s", hook_name, e)
            return HookResult(success=False, message=f"hook '{hook_name}' raised: {e}")

    cfg = _load_config()
    entry = cfg.get("hooks", {}).get(hook_name)
    if entry is None:
        return HookResult(
            success=False,
            message=f"Unknown hook '{hook_name}'. Known: {sorted(list_hooks().keys())}",
        )
    if entry.get("type") == "shell":
        return await _run_shell_hook(entry["command"], ctx)
    return HookResult(success=False, message=f"Unsupported hook type {entry.get('type')!r} for '{hook_name}'")
