"""
Utility functions for OpenCode Manager

File: app/mcp/opencode/utils.py
"""

import re
import hashlib
from typing import Tuple


def normalize_git_url(git_url: str) -> str:
    """
    Normalize a git URL to a canonical form

    Examples:
        git@github.com:user/repo.git → git@github.com:user/repo.git
        https://github.com/user/repo → git@github.com:user/repo.git
        https://github.com/user/repo.git → git@github.com:user/repo.git
        git@github.com:user/repo → git@github.com:user/repo.git

    Args:
        git_url: Git remote URL in various formats

    Returns:
        Normalized git URL (SSH format with .git suffix)
    """
    git_url = git_url.strip()

    # Convert HTTPS to SSH format
    if git_url.startswith("https://"):
        # https://github.com/user/repo[.git] → git@github.com:user/repo.git
        match = re.match(r"https://([^/]+)/(.+?)(?:\.git)?$", git_url)
        if match:
            host, path = match.groups()
            git_url = f"git@{host}:{path}.git"

    # Ensure .git suffix
    if not git_url.endswith(".git"):
        git_url += ".git"

    return git_url


def hash_git_url(git_url: str) -> str:
    """
    Generate a deterministic hash for a git URL

    This creates a unique identifier for a git repository.
    Note: OpenCode generates its own project ID, but we use this for file naming.

    Args:
        git_url: Normalized git URL

    Returns:
        Hex string (first 12 chars of SHA256 hash)
    """
    normalized = normalize_git_url(git_url)
    return hashlib.sha256(normalized.encode()).hexdigest()[:12]


def sanitize_for_filename(text: str) -> str:
    """
    Sanitize text for use in filenames/directory names

    Args:
        text: Text to sanitize

    Returns:
        Sanitized string safe for filesystem use
    """
    # Replace special chars with hyphens
    text = re.sub(r'[^\w\-_.]', '-', text)
    # Remove consecutive hyphens
    text = re.sub(r'-+', '-', text)
    # Remove leading/trailing hyphens
    text = text.strip('-')
    # Lowercase
    return text.lower()


def extract_repo_name(git_url: str) -> Tuple[str, str]:
    """
    Extract owner and repo name from git URL

    Args:
        git_url: Git URL (any format)

    Returns:
        Tuple of (owner, repo) or ("unknown", hash) if can't parse

    Examples:
        git@github.com:user/repo.git → ("user", "repo")
        https://github.com/user/repo → ("user", "repo")
    """
    # Try SSH format: git@host:owner/repo.git
    match = re.match(r"git@[^:]+:([^/]+)/(.+?)(?:\.git)?$", git_url)
    if match:
        owner, repo = match.groups()
        return (sanitize_for_filename(owner), sanitize_for_filename(repo))

    # Try HTTPS format: https://host/owner/repo[.git]
    match = re.match(r"https://[^/]+/([^/]+)/(.+?)(?:\.git)?$", git_url)
    if match:
        owner, repo = match.groups()
        return (sanitize_for_filename(owner), sanitize_for_filename(repo))

    # Fallback: use hash
    return ("unknown", hash_git_url(git_url))


def generate_project_name(git_url: str) -> str:
    """
    Generate a human-readable project name from git URL

    This is for display purposes only. Internal lookups use git_url.

    Args:
        git_url: Git URL

    Returns:
        Suggested project name (e.g., "owner-repo")
    """
    owner, repo = extract_repo_name(git_url)
    return f"{owner}-{repo}"


def generate_base_dir(git_url: str, custom_base: str = None) -> str:
    """
    Generate base directory path for a project

    Args:
        git_url: Git URL
        custom_base: Optional custom base directory

    Returns:
        Absolute path to base directory
    """
    if custom_base:
        return custom_base

    import os
    managed_dir = os.path.expanduser("~/.opencode-projects")
    project_name = generate_project_name(git_url)
    return os.path.join(managed_dir, project_name)
