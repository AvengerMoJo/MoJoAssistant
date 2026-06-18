"""SandboxManager — lifecycle orchestrator for coding agent sandboxes."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Iterator

from app.sandbox.backend import SandboxBackend
from app.sandbox.models import SandboxEntry
from app.sandbox.process import ProcessBackend

logger = logging.getLogger(__name__)

_DEFAULT_BASE = Path(os.path.expanduser("~/.memory/sandboxes"))


def _slug(repo_url: str) -> str:
    """Derive a filesystem-safe sandbox_id from a git URL."""
    name = repo_url.rstrip("/").split("/")[-1]
    name = re.sub(r"\.git$", "", name)
    owner = repo_url.rstrip("/").split("/")[-2].split(":")[-1]
    slug = re.sub(r"[^a-zA-Z0-9._-]", "-", f"{owner}-{name}").lower()
    return re.sub(r"-+", "-", slug).strip("-")


class SandboxManager:
    """
    Create, start, stop, and destroy coding agent sandboxes.

    Usage::

        mgr = SandboxManager()

        # Provision a new sandbox (clone repo, write meta.json)
        entry = mgr.create("git@github.com:org/repo.git", agent_type="opencode")

        # Start the agent process
        entry = mgr.start(entry.sandbox_id)

        # Get a live backend URL (starts the sandbox if it stopped)
        url = mgr.get_or_start(entry.sandbox_id)
        # → "http://127.0.0.1:4100" for opencode
        # → "/path/to/repo"         for claude_code

    Swap the backend for a different isolation layer::

        mgr = SandboxManager(backend=CubeSandboxBackend(...))
    """

    def __init__(
        self,
        backend: SandboxBackend | None = None,
        base_dir: Path | str | None = None,
    ) -> None:
        self._backend = backend or ProcessBackend()
        self._base = Path(base_dir) if base_dir else _DEFAULT_BASE
        self._base.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def create(
        self,
        repo_url: str,
        agent_type: str = "opencode",
        sandbox_id: str | None = None,
        existing_dir: str | None = None,
        password: str | None = None,
    ) -> SandboxEntry:
        """
        Provision a sandbox for *repo_url*.

        - *sandbox_id*: override the auto-generated slug.
        - *existing_dir*: point at an already-cloned repo; skip git clone.

        Returns the persisted SandboxEntry (status="stopped").
        """
        sid = sandbox_id or _slug(repo_url)

        # Idempotent: return existing entry unchanged
        try:
            existing = SandboxEntry.load(self._base, sid)
            logger.info("SandboxManager.create: sandbox %s already exists", sid)
            return existing
        except FileNotFoundError:
            pass

        working_dir = existing_dir or str(self._base / sid / "repo")
        entry = SandboxEntry(
            sandbox_id=sid,
            repo_url=repo_url,
            agent_type=agent_type,
            working_dir=working_dir,
            status="stopped",
            password=password,
        )
        entry = self._backend.create(entry, self._base)
        entry.save(self._base)
        logger.info("SandboxManager.create: provisioned %s", sid)
        return entry

    def start(self, sandbox_id: str) -> SandboxEntry:
        """Start the agent process.  Idempotent if already running."""
        entry = self._load(sandbox_id)
        entry = self._backend.status(entry)     # refresh live status

        if entry.status == "running":
            logger.info("SandboxManager.start: %s already running", sandbox_id)
            return entry

        logger.info("SandboxManager.start: starting %s", sandbox_id)
        entry = SandboxEntry(**{**entry.to_dict(), "status": "starting"})
        entry.save(self._base)
        try:
            entry = self._backend.start(entry)
        except Exception as exc:
            entry = SandboxEntry(**{**entry.to_dict(), "status": "failed", "last_error": str(exc)})
            entry.save(self._base)
            raise
        entry.save(self._base)
        return entry

    def stop(self, sandbox_id: str) -> SandboxEntry:
        """Stop the agent process."""
        entry = self._load(sandbox_id)
        entry = self._backend.stop(entry)
        entry.save(self._base)
        logger.info("SandboxManager.stop: %s stopped", sandbox_id)
        return entry

    def status(self, sandbox_id: str) -> SandboxEntry:
        """Return a fresh SandboxEntry reflecting live process state."""
        entry = self._load(sandbox_id)
        entry = self._backend.status(entry)
        entry.save(self._base)
        return entry

    def destroy(self, sandbox_id: str) -> None:
        """Stop the agent and delete the sandbox directory + meta."""
        entry = self._load(sandbox_id)
        self._backend.destroy(entry, self._base)
        logger.info("SandboxManager.destroy: %s removed", sandbox_id)

    def get_or_start(self, sandbox_id: str) -> str:
        """
        Return the live access URL (or working_dir for claude_code).
        Starts the sandbox if it is stopped or failed.

        This is the primary entry point for the CODING_SESSION handler.
        """
        entry = self.status(sandbox_id)
        if entry.status != "running":
            entry = self.start(sandbox_id)
        if entry.agent_type == "claude_code":
            return entry.working_dir
        return f"http://127.0.0.1:{entry.port}"

    def list(self) -> list[SandboxEntry]:
        """List all known sandboxes with refreshed status."""
        entries = []
        for meta in self._base.glob("*/meta.json"):
            try:
                entry = SandboxEntry.load(self._base, meta.parent.name)
                entry = self._backend.status(entry)
                entry.save(self._base)
                entries.append(entry)
            except Exception as exc:
                logger.warning("SandboxManager.list: skipping %s — %s", meta, exc)
        return entries

    def get(self, sandbox_id: str) -> SandboxEntry:
        """Return a sandbox entry by ID without refreshing status."""
        return self._load(sandbox_id)

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _load(self, sandbox_id: str) -> SandboxEntry:
        try:
            return SandboxEntry.load(self._base, sandbox_id)
        except FileNotFoundError:
            raise ValueError(
                f"Sandbox '{sandbox_id}' not found. "
                f"Run sandbox_create first, or check ~/.memory/sandboxes/."
            )
