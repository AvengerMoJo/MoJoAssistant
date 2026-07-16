"""
Project registry — durable label → project spec resolution.

Lets any assistant request a coding sandbox by a human-typeable label like
"opencode+python+mcp-buffer" instead of needing to know exact git URLs, SSH
key paths, or which of the underlying systems (SandboxManager for the LLM
tool-loop, OpenCodeManager/BackendRegistry for coding_agent-executor roles)
actually owns that project.

Label format: "<agent>+<stack>+<repo>" or "<agent>+<repo>" (stack omitted).
  agent: "opencode" | "claude_code" | "loop"
         ("loop" = plain LLM tool-loop sandbox via SandboxManager, no coding agent)
  stack: informational hint (python, node, ...) — not currently used to pick
         a backend/image, reserved for future per-stack provisioning
  repo:  short registry key. Must already be registered, or the caller must
         supply git_url in the same call to auto-register it.

Config: ~/.memory/config/project_registry.json
{
  "projects": {
    "mcp-buffer": {
      "git_url": "https://github.com/AvengerMoJo/mcp-buffer",
      "stack": "python",
      "preferred_agent": "opencode",
      "description": "MCP buffer file/link service"
    }
  }
}
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path.home() / ".memory" / "config" / "project_registry.json"


@dataclass
class ProjectSpec:
    repo: str
    git_url: str
    stack: str = ""
    preferred_agent: str = "opencode"
    description: str = ""
    # Which sandbox/hooks.py hook prepares this repo's checkout. Default
    # preserves old behavior (bare `git clone`, whatever host auth exists).
    # Set to "git_clone_public_https" for public repos to avoid needing any
    # SSH credentials at all — see the mcp-buffer registration for an example.
    prepare_hook: str = "git_clone_default"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, repo: str, d: Dict[str, Any]) -> "ProjectSpec":
        return cls(
            repo=repo,
            git_url=d.get("git_url", ""),
            stack=d.get("stack", ""),
            preferred_agent=d.get("preferred_agent", "opencode"),
            description=d.get("description", ""),
            prepare_hook=d.get("prepare_hook", "git_clone_default"),
        )


def parse_label(label: str) -> Tuple[str, str, str]:
    """Parse "agent+stack+repo" or "agent+repo" into (agent, stack, repo).

    Raises ValueError if the label doesn't have 2 or 3 '+'-separated parts.
    """
    parts = label.split("+")
    if len(parts) == 3:
        agent, stack, repo = parts
    elif len(parts) == 2:
        agent, repo = parts
        stack = ""
    else:
        raise ValueError(
            f"Label {label!r} must be 'agent+repo' or 'agent+stack+repo' "
            "(e.g. 'opencode+python+mcp-buffer')"
        )
    agent, stack, repo = agent.strip(), stack.strip(), repo.strip()
    if not agent or not repo:
        raise ValueError(f"Label {label!r} has an empty agent or repo component")
    return agent, stack, repo


def _load_registry() -> Dict[str, Any]:
    if not _REGISTRY_PATH.exists():
        return {"projects": {}}
    try:
        return json.loads(_REGISTRY_PATH.read_text())
    except Exception as e:
        logger.warning("project_registry: failed to load %s: %s", _REGISTRY_PATH, e)
        return {"projects": {}}


def _save_registry(data: Dict[str, Any]) -> None:
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _REGISTRY_PATH.with_suffix(_REGISTRY_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(_REGISTRY_PATH)


def register_project(
    repo: str,
    git_url: str,
    stack: str = "",
    preferred_agent: str = "opencode",
    description: str = "",
    prepare_hook: str = "git_clone_default",
) -> ProjectSpec:
    """Register (or overwrite) a project under its short repo key."""
    data = _load_registry()
    spec = ProjectSpec(
        repo=repo, git_url=git_url, stack=stack,
        preferred_agent=preferred_agent, description=description,
        prepare_hook=prepare_hook,
    )
    data.setdefault("projects", {})[repo] = {
        "git_url": spec.git_url,
        "stack": spec.stack,
        "preferred_agent": spec.preferred_agent,
        "description": spec.description,
        "prepare_hook": spec.prepare_hook,
    }
    _save_registry(data)
    logger.info("project_registry: registered '%s' -> %s (hook=%s)", repo, git_url, prepare_hook)
    return spec


def get_project(repo: str) -> Optional[ProjectSpec]:
    data = _load_registry()
    entry = data.get("projects", {}).get(repo)
    if entry is None:
        return None
    return ProjectSpec.from_dict(repo, entry)


def resolve(
    repo: str,
    git_url: Optional[str] = None,
    stack: Optional[str] = None,
    agent: Optional[str] = None,
    prepare_hook: Optional[str] = None,
) -> ProjectSpec:
    """Resolve a repo key to its ProjectSpec.

    If the repo is already registered, returns the stored spec (any of
    git_url/stack/agent/prepare_hook passed here are ignored — the registry
    is the source of truth once a project exists).

    If not registered:
      - and git_url is provided, auto-registers it and returns the new spec.
        Pass prepare_hook to pick a non-default checkout strategy at
        registration time (e.g. "git_clone_public_https" for a public repo).
      - and git_url is NOT provided, raises ValueError with guidance.
    """
    existing = get_project(repo)
    if existing is not None:
        return existing
    if not git_url:
        raise ValueError(
            f"Project '{repo}' is not registered and no git_url was supplied. "
            "Provide git_url the first time you reference this repo, e.g. "
            f"sandbox_request(kind='project', label='opencode+{repo}', git_url='<url>')."
        )
    return register_project(
        repo=repo,
        git_url=git_url,
        stack=stack or "",
        preferred_agent=agent or "opencode",
        prepare_hook=prepare_hook or "git_clone_default",
    )


def list_projects() -> List[ProjectSpec]:
    data = _load_registry()
    return [ProjectSpec.from_dict(repo, entry) for repo, entry in data.get("projects", {}).items()]
