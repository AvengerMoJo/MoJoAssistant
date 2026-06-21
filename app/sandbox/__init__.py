"""Sandbox module — coding agent lifecycle management."""
from app.sandbox.backend import SandboxBackend
from app.sandbox.manager import SandboxManager
from app.sandbox.models import SandboxEntry
from app.sandbox.process import ProcessBackend

__all__ = ["SandboxBackend", "SandboxEntry", "SandboxManager", "ProcessBackend"]
