"""
Git identity resolver — loads per-repo git attribution config.

Ensures commits made by coding agents inside sandboxes are attributed to the
real user, not 'opencode@local'. Supports per-repo email overrides (e.g.
personal vs business) and an assistant attribution trailer.

Config file: ~/.memory/config/git_identity.json

{
  "default": {
    "name": "Alex",
    "email": "alex@personal.com",
    "assistant_attribution": "Assistant Popo@MoJoAssistant Implementation"
  },
  "overrides": {
    "company-org/repo": {
      "email": "alex@company.com",
      "assistant_attribution": "Assistant Popo@MoJoAssistant Implementation"
    }
  }
}
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GitIdentity:
    name: str
    email: str
    assistant_attribution: Optional[str] = None

    @property
    def commit_trailer(self) -> str:
        """Git trailer for assistant attribution, or empty string."""
        if self.assistant_attribution:
            return f"\n\n{self.assistant_attribution}"
        return ""

    def to_env(self) -> dict:
        """Environment vars for GIT_AUTHOR_* and GIT_COMMITTER_*."""
        return {
            "GIT_AUTHOR_NAME": self.name,
            "GIT_AUTHOR_EMAIL": self.email,
            "GIT_COMMITTER_NAME": self.name,
            "GIT_COMMITTER_EMAIL": self.email,
        }


def _config_path() -> Path:
    return Path(os.path.expanduser("~/.memory/config/git_identity.json"))


def _extract_repo_key(repo_url: str) -> str:
    """Extract 'org/repo' from a git URL for matching overrides.

    git@github.com:AvengerMoJo/mcp-service.git → AvengerMoJo/mcp-service
    https://github.com/AvengerMoJo/mcp-service.git → AvengerMoJo/mcp-service
    """
    m = re.search(r'[:/]([^/]+/[^/]+?)(?:\.git)?$', repo_url)
    return m.group(1) if m else repo_url


def load_git_identity(repo_url: str = "") -> GitIdentity:
    """Load git identity for a repo, falling back to defaults.

    Resolution order:
      1. Per-repo override matching org/repo key
      2. Default config
      3. Hardcoded fallback
    """
    config_file = _config_path()

    if config_file.exists():
        try:
            data = json.loads(config_file.read_text())
            repo_key = _extract_repo_key(repo_url) if repo_url else ""

            # Check per-repo override
            if repo_key and repo_key in data.get("overrides", {}):
                override = data["overrides"][repo_key]
                default = data.get("default", {})
                return GitIdentity(
                    name=override.get("name", default.get("name", "Alex")),
                    email=override["email"],
                    assistant_attribution=override.get(
                        "assistant_attribution",
                        default.get("assistant_attribution"),
                    ),
                )

            # Use default
            default = data.get("default", {})
            if default.get("name") and default.get("email"):
                return GitIdentity(
                    name=default["name"],
                    email=default["email"],
                    assistant_attribution=default.get("assistant_attribution"),
                )
        except Exception as e:
            logger.warning("Failed to load git_identity.json: %s", e)

    # Hardcoded fallback
    return GitIdentity(name="Alex", email="avengermojo@gmail.com")


def configure_repo_git_identity(repo_dir: str | Path, identity: GitIdentity) -> None:
    """Set git user.name and user.email in a repo (local config, not global).

    Called after cloning, before the coding agent starts.
    """
    repo_path = Path(repo_dir)
    if not (repo_path / ".git").exists():
        logger.warning("configure_repo_git_identity: %s is not a git repo", repo_path)
        return

    try:
        subprocess.run(
            ["git", "config", "user.name", identity.name],
            cwd=str(repo_path), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", identity.email],
            cwd=str(repo_path), check=True, capture_output=True,
        )
        logger.info(
            "Git identity set for %s: %s <%s>",
            repo_path.name, identity.name, identity.email,
        )
    except Exception as e:
        logger.warning("Failed to set git identity for %s: %s", repo_path, e)
