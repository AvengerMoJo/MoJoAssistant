"""Shared log emit for scheduler components.

Scheduler._log has always printed to stdout when no logger is wired, which is
why [Scheduler] lines reach the journal. The executors and the resource pool
guarded on `if self._logger:` with no else, so with logger=None (how the
scheduler is built) every line -- including 'LLM call failed' -- vanished.
Found 2026-10-08 while a failed run left no trace of why it failed.
"""
from datetime import datetime


def emit(logger, component: str, message: str, level: str = "info") -> None:
    if logger:
        getattr(logger, level)(f"[{component}] {message}")
        return
    if level == "debug":
        return
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tag = "" if level == "info" else f" {level.upper()}"
    print(f"[{stamp}] [{component}]{tag} {message}", flush=True)
