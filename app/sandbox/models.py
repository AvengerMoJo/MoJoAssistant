"""Sandbox data model."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class SandboxEntry:
    """One sandbox — a repo directory plus an optional long-lived agent process."""

    sandbox_id: str          # slug derived from repo URL, e.g. "jumpstartmojo-bsl"
    repo_url: str            # canonical git remote, e.g. "git@github.com:org/repo.git"
    agent_type: str          # "opencode" | "claude_code"
    working_dir: str         # absolute path to the cloned repo
    status: str = "stopped"  # "stopped" | "starting" | "running" | "failed"
    port: int | None = None  # None for claude_code (no HTTP server)
    pid: int | None = None
    password: str | None = None  # OPENCODE_SERVER_PASSWORD; None = unsecured
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_error: str | None = None

    # ------------------------------------------------------------------ #
    #  Persistence                                                         #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SandboxEntry:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self, base_dir: Path) -> None:
        meta = base_dir / self.sandbox_id / "meta.json"
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, base_dir: Path, sandbox_id: str) -> SandboxEntry:
        meta = base_dir / sandbox_id / "meta.json"
        if not meta.exists():
            raise FileNotFoundError(f"Sandbox not found: {sandbox_id}")
        return cls.from_dict(json.loads(meta.read_text()))
