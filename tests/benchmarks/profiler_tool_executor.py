"""ProfilerExecutionContext — sandboxed tool stubs for the routing profiler.

A10 found that cells B/C/D of the A8 task set are tool-execution tasks
(read_file, write_file, list_files, bash_exec), but the v2 profiler only
did single-shot chat completions — so models that tried to call tools
returned empty content and failed check_answer, while prose-only
responses sometimes "passed" without doing the work.

This module implements just the four tool primitives the A8 tasks need,
with a strict sandbox:

  - read_file:  allowed roots are ~/.memory/ and the project repo.
  - write_file: ONLY the scratch dir; everything else is denied.
  - list_files: same allow-list as read_file.
  - bash_exec:  cwd locked to scratch; no ``cd ..``; 10s timeout.

The context is sync — file I/O and subprocess.run are blocking. The
profiler wraps calls in asyncio.to_thread if it needs to be async-safe
(caller's call site will decide).

Companion spec: ~/.memory/research/profiler_tool_execution_fix.md
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# Tools this context understands. Other names get a clear "unknown" error
# so the model gets feedback instead of silent ignore.
KNOWN_TOOLS = {"read_file", "write_file", "list_files", "bash_exec"}

# Max bytes returned from read_file. The cell-A/B context files are small;
# 8KB is plenty for any A8 task and prevents a pathological read from
# blowing up the next LLM call's context window.
READ_MAX_BYTES = 8192

# Bash timeout. A8 cell-B tasks use bash for "wc -l" and "ls" — 10s is
# overkill but cheap. The timeout exists to bound blast radius.
BASH_TIMEOUT_S = 10.0


def _resolve(path_str: str, allowed_roots: List[Path]) -> Path:
    """Resolve a path string against the working directory to its REAL target,
    collapsing ``..`` and following symlinks. Does NOT enforce the allow-list
    (caller decides via _is_under).

    ``.resolve()`` is essential for sandbox safety: without it a path like
    ``<root>/../../etc/passwd`` lexically appears "under" root (relative_to
    matches the prefix) but resolves outside it — a path-traversal escape
    affecting read_file/write_file/list_files. Symlink resolution likewise
    blocks ``<root>/link -> /etc``. The prior code avoided resolve() fearing
    symlink escapes, but that reasoning was inverted: resolve() is what
    PREVENTS them. strict=False (the default) so not-yet-existing write
    targets still normalize.
    """
    if not path_str:
        raise ValueError("empty path")
    p = Path(os.path.expanduser(path_str))
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def _is_under(path: Path, root: Path) -> bool:
    """True if path is the same as or strictly inside root.

    Both sides are resolved first so ``..`` components and symlinks can't
    make an outside path appear inside (defense-in-depth alongside _resolve,
    which already resolves the path; resolving again here is idempotent and
    keeps direct callers of _is_under safe).
    """
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


@dataclass
class ToolResult:
    """Outcome of a single tool execution. Always JSON-serializable.

    ``ok`` is True for a successful tool call; ``error`` carries a short
    reason when False. ``elapsed_s`` is wall-clock for the call.
    ``content`` is the optional tool output (truncated to fit in the
    next LLM call's context window).
    """
    tool: str
    args: Dict[str, Any]
    ok: bool
    elapsed_s: float = 0.0
    content: str = ""
    error: str = ""

    def to_message(self) -> Dict[str, Any]:
        """Build the OpenAI-shape tool-result message LMStudio expects.

        Shape: {"role": "tool", "tool_call_id": <id>, "content": <json str>}.
        The ``tool_call_id`` is filled by the caller; this returns the
        per-call body. We embed ``ok`` and ``error`` in the JSON so the
        model can see why a tool failed.
        """
        payload: Dict[str, Any] = {"ok": self.ok}
        if self.error:
            payload["error"] = self.error
        if self.content:
            payload["content"] = self.content
        return payload


class ProfilerExecutionContext:
    """Sandboxed tool dispatcher for the routing profiler.

    One context per task (so the task's scratch dir / setup can be
    reflected if needed). Sync interface; the caller's loop wraps in
    asyncio.to_thread if needed.

    The allowed_roots list is computed at construction time from the
    user's home + the project root. Tests can override via the
    ``allowed_roots`` constructor arg.
    """

    def __init__(
        self,
        task: Dict[str, Any],
        *,
        scratch_dir: Optional[Path] = None,
        allowed_roots: Optional[List[Path]] = None,
    ) -> None:
        self.task = task
        self.scratch_dir = scratch_dir or (Path.home() / ".memory" / "benchmarks" / "routing" / "scratch")
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        # Default allow-list: ~/.memory and the project repo. Tests pass
        # a custom list.
        if allowed_roots is None:
            self.allowed_roots: List[Path] = [
                Path.home() / ".memory",
                # PROJECT_ROOT: imported lazily to keep this module
                # importable without sys.path tricks.
                _project_root(),
            ]
        else:
            self.allowed_roots = allowed_roots
        self.call_log: List[ToolResult] = []

    # ------------------------------------------------------------------
    # Public dispatch
    # ------------------------------------------------------------------

    def execute(self, tool_name: str, args: Dict[str, Any]) -> ToolResult:
        """Dispatch a tool call. Records into self.call_log.

        Args that arrive as JSON strings (OpenAI wire format) are parsed
        here so individual tool methods can assume dict input.
        """
        import time as _time
        start = _time.time()

        # OpenAI sometimes sends arguments as a JSON string; normalize.
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                result = ToolResult(tool=tool_name, args={}, ok=False,
                                    error=f"arguments not valid JSON: {args!r}")
                self.call_log.append(result)
                return result

        if tool_name not in KNOWN_TOOLS:
            result = ToolResult(tool=tool_name, args=args, ok=False,
                                error=f"unknown tool '{tool_name}'. "
                                      f"Known: {sorted(KNOWN_TOOLS)}")
            self.call_log.append(result)
            return result

        method = getattr(self, tool_name)
        result = method(args)
        result.tool = tool_name
        result.args = args
        result.elapsed_s = round(_time.time() - start, 3)
        self.call_log.append(result)
        return result

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def read_file(self, args: Dict[str, Any]) -> ToolResult:
        path_str = args.get("path") or args.get("file") or ""
        try:
            path = _resolve(path_str, self.allowed_roots)
        except ValueError:
            return ToolResult(tool="read_file", args=args, ok=False,
                              error="path is required")
        if not any(_is_under(path, root) for root in self.allowed_roots):
            return ToolResult(tool="read_file", args=args, ok=False,
                              error=f"path outside allow-list: {path}",
                              content=f"allowed_roots={[str(r) for r in self.allowed_roots]}")
        if not path.exists():
            return ToolResult(tool="read_file", args=args, ok=False,
                              error=f"file not found: {path}")
        if not path.is_file():
            return ToolResult(tool="read_file", args=args, ok=False,
                              error=f"not a regular file: {path}")
        try:
            content = path.read_text(errors="replace")[:READ_MAX_BYTES]
            return ToolResult(tool="read_file", args=args, ok=True, content=content)
        except Exception as e:
            return ToolResult(tool="read_file", args=args, ok=False,
                              error=f"read failed: {e}")

    def write_file(self, args: Dict[str, Any]) -> ToolResult:
        path_str = args.get("path") or ""
        content = args.get("content") or ""
        if not path_str:
            return ToolResult(tool="write_file", args=args, ok=False,
                              error="path is required")
        try:
            path = _resolve(path_str, self.allowed_roots)
        except ValueError:
            return ToolResult(tool="write_file", args=args, ok=False,
                              error="path is required")
        if not _is_under(path, self.scratch_dir):
            return ToolResult(tool="write_file", args=args, ok=False,
                              error=f"write_file denied: only scratch dir is writable "
                                    f"(allowed: {self.scratch_dir})",
                              content=f"requested_path={path}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return ToolResult(tool="write_file", args=args, ok=True,
                              content=f"wrote {len(content)} bytes to {path}")
        except Exception as e:
            return ToolResult(tool="write_file", args=args, ok=False,
                              error=f"write failed: {e}")

    def list_files(self, args: Dict[str, Any]) -> ToolResult:
        path_str = args.get("path") or args.get("dir") or ""
        if not path_str:
            return ToolResult(tool="list_files", args=args, ok=False,
                              error="path is required")
        try:
            path = _resolve(path_str, self.allowed_roots)
        except ValueError:
            return ToolResult(tool="list_files", args=args, ok=False,
                              error="path is required")
        if not any(_is_under(path, root) for root in self.allowed_roots):
            return ToolResult(tool="list_files", args=args, ok=False,
                              error=f"path outside allow-list: {path}")
        if not path.exists():
            return ToolResult(tool="list_files", args=args, ok=False,
                              error=f"directory not found: {path}")
        if not path.is_dir():
            return ToolResult(tool="list_files", args=args, ok=False,
                              error=f"not a directory: {path}")
        try:
            entries = sorted([p.name + ("/" if p.is_dir() else "")
                              for p in path.iterdir()])
            return ToolResult(tool="list_files", args=args, ok=True,
                              content="\n".join(entries))
        except Exception as e:
            return ToolResult(tool="list_files", args=args, ok=False,
                              error=f"list failed: {e}")

    def bash_exec(self, args: Dict[str, Any]) -> ToolResult:
        cmd = args.get("command") or args.get("cmd") or ""
        if not cmd.strip():
            return ToolResult(tool="bash_exec", args=args, ok=False,
                              error="command is required")
        # Sandbox: forbid `cd` entirely. cwd is locked to scratch and the model
        # has read_file/list_files for paths outside scratch, so cd is never
        # needed — and it's an escape vector: "cd ~", "cd $HOME", and "cd ./.."
        # (the "./" prefix bypasses a narrower "cd .." regex) all climb out.
        # Forbidding any cd keeps relative commands rooted in scratch.
        if re.search(r"\bcd\b", cmd):
            return ToolResult(tool="bash_exec", args=args, ok=False,
                              error="bash_exec denied: cd above scratch not allowed")
        if cmd.strip().startswith("/"):
            return ToolResult(tool="bash_exec", args=args, ok=False,
                              error="bash_exec denied: absolute paths not allowed")
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=self.scratch_dir,
                capture_output=True, text=True, timeout=BASH_TIMEOUT_S,
            )
            out = proc.stdout
            err = proc.stderr
            # Truncate huge output to keep the next LLM call's context sane.
            truncated = (len(out) + len(err)) > READ_MAX_BYTES
            if truncated:
                out = out[:READ_MAX_BYTES // 2]
                err = err[:READ_MAX_BYTES // 2]
            content = f"returncode={proc.returncode}\nstdout:\n{out}\nstderr:\n{err}"
            if truncated:
                content += "\n[output truncated]"
            # Non-zero return is not a tool error — the command ran.
            return ToolResult(tool="bash_exec", args=args, ok=True, content=content)
        except subprocess.TimeoutExpired:
            return ToolResult(tool="bash_exec", args=args, ok=False,
                              error=f"command timed out after {BASH_TIMEOUT_S}s")
        except Exception as e:
            return ToolResult(tool="bash_exec", args=args, ok=False,
                              error=f"bash failed: {e}")


def _project_root() -> Path:
    """Locate the project root via this file's path. The profiler lives in
    tests/benchmarks/, two levels below PROJECT_ROOT.

    Falls back to the current working directory if the expected layout
    isn't found (e.g. when running from a worktree).
    """
    here = Path(__file__).resolve()
    candidate = here.parent.parent.parent  # tests/benchmarks/profiler_tool_executor.py → PROJECT_ROOT
    if (candidate / "app").exists():
        return candidate
    return Path.cwd().resolve()