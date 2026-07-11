"""Tests for ProfilerExecutionContext — A11.1.

Covers the four tool primitives, sandbox enforcement, and ToolResult
serialization. Pure unit tests — no LMStudio / GPU involved.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make the profiler module importable.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "benchmarks"))

from profiler_tool_executor import (  # noqa: E402
    KNOWN_TOOLS,
    ProfilerExecutionContext,
    ToolResult,
    _is_under,
    _resolve,
)


class TestReadFile(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        # Set up the context with explicit roots.
        self.readable = self.tmpdir / "readable"
        self.readable.mkdir()
        self.scratch = self.tmpdir / "scratch"
        self.scratch.mkdir()
        self.secret = self.tmpdir / "secret"
        self.secret.mkdir()
        self.secret_file = self.secret / "credentials.txt"
        self.secret_file.write_text("top secret")
        self.ctx = ProfilerExecutionContext(
            task={},
            scratch_dir=self.scratch,
            allowed_roots=[self.readable, self.tmpdir / "repo"],
        )
        self.ok_file = self.readable / "ok.txt"
        self.ok_file.write_text("hello world")

    def test_reads_allowed_file(self):
        r = self.ctx.execute("read_file", {"path": str(self.ok_file)})
        self.assertTrue(r.ok, r.error)
        self.assertEqual(r.content, "hello world")
        self.assertEqual(r.tool, "read_file")
        # elapsed_s is rounded to 3 decimals; fast file ops can be 0.000.
        # The contract is ">= 0", not "> 0".
        self.assertGreaterEqual(r.elapsed_s, 0.0)

    def test_denies_path_outside_allow_list(self):
        r = self.ctx.execute("read_file", {"path": str(self.secret_file)})
        self.assertFalse(r.ok)
        self.assertIn("allow-list", r.error)
        # Helpful error includes the denied path so the model can adjust.
        self.assertIn("credentials.txt", r.error)

    def test_missing_file_returns_error_not_crash(self):
        r = self.ctx.execute("read_file", {"path": str(self.readable / "nope.txt")})
        self.assertFalse(r.ok)
        self.assertIn("not found", r.error)

    def test_directory_returns_error(self):
        r = self.ctx.execute("read_file", {"path": str(self.readable)})
        self.assertFalse(r.ok)
        self.assertIn("not a regular file", r.error)

    def test_empty_path_returns_error(self):
        r = self.ctx.execute("read_file", {"path": ""})
        self.assertFalse(r.ok)
        self.assertIn("path is required", r.error)

    def test_denies_dotdot_traversal_read(self):
        # <allowed_root>/../<outside> must NOT pass the allow-list just because
        # it lexically starts with the root prefix. Without resolve() the
        # relative_to check matches the prefix and the read escapes.
        outside = self.tmpdir / "outside.txt"
        outside.write_text("secret")
        traversal = str(self.readable) + "/../outside.txt"
        r = self.ctx.execute("read_file", {"path": traversal})
        self.assertFalse(r.ok, r.error)
        self.assertIn("allow-list", r.error)
        self.assertNotIn("secret", r.content)


class TestWriteFile(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.scratch = self.tmpdir / "scratch"
        self.scratch.mkdir()
        self.ctx = ProfilerExecutionContext(
            task={},
            scratch_dir=self.scratch,
            allowed_roots=[self.tmpdir / "memory"],
        )

    def test_write_to_scratch_succeeds(self):
        target = self.scratch / "cellB_001.txt"
        r = self.ctx.execute("write_file", {"path": str(target), "content": "25"})
        self.assertTrue(r.ok, r.error)
        self.assertEqual(target.read_text(), "25")

    def test_create_subdirs_under_scratch(self):
        target = self.scratch / "nested" / "deep" / "cellD_005.txt"
        r = self.ctx.execute("write_file", {"path": str(target), "content": "x"})
        self.assertTrue(r.ok, r.error)
        self.assertTrue(target.exists())

    def test_denies_write_to_repo(self):
        # Attempt to write outside scratch — even if it's in allowed_roots for reads.
        repo_file = self.tmpdir / "repo" / "evil.txt"
        repo_file.parent.mkdir(parents=True, exist_ok=True)
        r = self.ctx.execute("write_file", {"path": str(repo_file), "content": "x"})
        self.assertFalse(r.ok)
        self.assertIn("scratch dir", r.error)
        # File must not exist.
        self.assertFalse(repo_file.exists())

    def test_denies_write_to_home(self):
        r = self.ctx.execute("write_file",
                            {"path": "~/.memory/evil.txt", "content": "x"})
        self.assertFalse(r.ok)
        self.assertIn("scratch dir", r.error)

    def test_denies_dotdot_write_traversal(self):
        # scratch/../<outside> must not write outside scratch. This is the
        # dangerous direction — without resolve() a model could write
        # anywhere by climbing out of scratch lexically.
        target = str(self.scratch) + "/../evil.txt"
        r = self.ctx.execute("write_file", {"path": target, "content": "x"})
        self.assertFalse(r.ok, r.error)
        self.assertIn("scratch dir", r.error)
        # Confirm nothing was written just outside scratch.
        self.assertFalse((self.scratch.parent / "evil.txt").exists())


class TestListFiles(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.readable = self.tmpdir / "readable"
        self.readable.mkdir()
        (self.readable / "a.txt").write_text("a")
        (self.readable / "b.txt").write_text("b")
        (self.readable / "sub").mkdir()
        self.scratch = self.tmpdir / "scratch"
        self.scratch.mkdir()
        self.ctx = ProfilerExecutionContext(
            task={},
            scratch_dir=self.scratch,
            allowed_roots=[self.readable],
        )

    def test_lists_files_and_dirs(self):
        r = self.ctx.execute("list_files", {"path": str(self.readable)})
        self.assertTrue(r.ok, r.error)
        self.assertIn("a.txt", r.content)
        self.assertIn("b.txt", r.content)
        self.assertIn("sub/", r.content)

    def test_denies_outside_allow_list(self):
        secret_dir = self.tmpdir / "secret"
        secret_dir.mkdir()
        r = self.ctx.execute("list_files", {"path": str(secret_dir)})
        self.assertFalse(r.ok)
        self.assertIn("allow-list", r.error)

    def test_missing_dir_returns_error(self):
        r = self.ctx.execute("list_files", {"path": str(self.readable / "nope")})
        self.assertFalse(r.ok)
        self.assertIn("not found", r.error)

    def test_file_path_returns_error(self):
        r = self.ctx.execute("list_files", {"path": str(self.readable / "a.txt")})
        self.assertFalse(r.ok)
        self.assertIn("not a directory", r.error)


class TestBashExec(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.scratch = self.tmpdir / "scratch"
        self.scratch.mkdir()
        (self.scratch / "data.txt").write_text("one\ntwo\nthree\n")
        self.ctx = ProfilerExecutionContext(
            task={},
            scratch_dir=self.scratch,
            allowed_roots=[self.tmpdir / "memory"],
        )

    def test_runs_simple_command(self):
        r = self.ctx.execute("bash_exec", {"command": "echo hi"})
        self.assertTrue(r.ok)
        self.assertIn("hi", r.content)
        self.assertIn("returncode=0", r.content)

    def test_runs_in_scratch_cwd(self):
        # wc -l on data.txt should report 3 lines.
        r = self.ctx.execute("bash_exec", {"command": "wc -l data.txt"})
        self.assertTrue(r.ok, r.error)
        self.assertIn("3", r.content)

    def test_denies_cd_dotdot(self):
        r = self.ctx.execute("bash_exec", {"command": "cd .. && ls"})
        self.assertFalse(r.ok)
        self.assertIn("cd above scratch", r.error)

    def test_denies_cd_absolute(self):
        r = self.ctx.execute("bash_exec", {"command": "cd /tmp && ls"})
        self.assertFalse(r.ok)
        self.assertIn("cd above scratch", r.error)

    def test_denies_absolute_path_prefix(self):
        r = self.ctx.execute("bash_exec", {"command": "/bin/echo hi"})
        self.assertFalse(r.ok)
        self.assertIn("absolute paths", r.error)

    def test_non_zero_return_is_ok(self):
        # A command that exits non-zero is not a tool error — the bash
        # call itself succeeded. The model should see the returncode.
        r = self.ctx.execute("bash_exec", {"command": "ls /nope"})
        self.assertTrue(r.ok)  # tool worked
        self.assertIn("returncode=", r.content)
        self.assertNotEqual("returncode=0", r.content.split("\n")[0])

    def test_denies_cd_home(self):
        # "cd ~" was not caught by the old "\bcd\s+\.\." / "\bcd\s+/" regex.
        r = self.ctx.execute("bash_exec", {"command": "cd ~ && ls"})
        self.assertFalse(r.ok)
        self.assertIn("cd above scratch", r.error)

    def test_denies_cd_dot_slash_dotdot(self):
        # "cd ./.." bypassed the old "\bcd\s+\.\." regex via the "./" prefix.
        r = self.ctx.execute("bash_exec", {"command": "cd ./.. && ls"})
        self.assertFalse(r.ok)
        self.assertIn("cd above scratch", r.error)

    def test_denies_any_cd(self):
        # cd is forbidden entirely — cwd is scratch and the model has other
        # tools for paths outside it. Even cd into a subdir is rejected.
        r = self.ctx.execute("bash_exec", {"command": "cd subdir && ls"})
        self.assertFalse(r.ok)
        self.assertIn("cd above scratch", r.error)


class TestUnknownTool(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = ProfilerExecutionContext(
            task={},
            scratch_dir=Path(self.tmp.name),
            allowed_roots=[],
        )

    def test_unknown_tool_returns_clear_error(self):
        r = self.ctx.execute("memory_search", {"query": "test"})
        self.assertFalse(r.ok)
        self.assertIn("unknown tool", r.error)
        # Helpful: the model should see what tools ARE available.
        self.assertIn("read_file", r.error)
        self.assertIn("bash_exec", r.error)

    def test_known_tools_constant(self):
        # Lock the set of supported tools so a typo in a tool name fails
        # loud at the test boundary, not at runtime.
        self.assertEqual(KNOWN_TOOLS, {"read_file", "write_file", "list_files", "bash_exec"})


class TestDispatchEdgeCases(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.scratch = self.tmpdir / "scratch"
        self.scratch.mkdir()
        self.ctx = ProfilerExecutionContext(
            task={},
            scratch_dir=self.scratch,
            allowed_roots=[self.tmpdir / "memory"],
        )

    def test_arguments_as_json_string(self):
        # OpenAI sometimes sends arguments as a JSON string; the
        # dispatcher must parse it.
        target = self.scratch / "x.txt"
        r = self.ctx.execute("write_file",
                            json.dumps({"path": str(target), "content": "ok"}))
        self.assertTrue(r.ok, r.error)
        self.assertEqual(target.read_text(), "ok")

    def test_invalid_json_arguments_return_error(self):
        r = self.ctx.execute("write_file", "{not valid json")
        self.assertFalse(r.ok)
        self.assertIn("not valid JSON", r.error)

    def test_call_log_records_all_calls(self):
        self.ctx.execute("bash_exec", {"command": "echo a"})
        self.ctx.execute("bash_exec", {"command": "echo b"})
        self.ctx.execute("bash_exec", {"command": "cd .."})
        self.assertEqual(len(self.ctx.call_log), 3)
        # First two are ok, third failed.
        self.assertTrue(self.ctx.call_log[0].ok)
        self.assertTrue(self.ctx.call_log[1].ok)
        self.assertFalse(self.ctx.call_log[2].ok)

    def test_tool_result_to_message_shape(self):
        r = ToolResult(tool="read_file", args={"path": "/x"}, ok=True,
                       content="hello")
        msg = r.to_message()
        self.assertEqual(msg, {"ok": True, "content": "hello"})

        r2 = ToolResult(tool="write_file", args={}, ok=False, error="denied")
        msg2 = r2.to_message()
        self.assertEqual(msg2, {"ok": False, "error": "denied"})


class TestPathHelpers(unittest.TestCase):
    """Lower-level: _resolve and _is_under. Tested directly so future
    refactors don't break the sandbox contract."""

    def test_resolve_absolute_path_passes_through(self):
        p = _resolve("/etc/passwd", [Path("/etc")])
        self.assertEqual(p, Path("/etc/passwd"))

    def test_resolve_relative_path_uses_cwd(self):
        p = _resolve("foo/bar", [])
        # Not absolute before resolution; after, should be cwd/foo/bar.
        self.assertTrue(p.is_absolute())
        self.assertEqual(p.name, "bar")

    def test_resolve_expands_user(self):
        p = _resolve("~/foo", [])
        self.assertTrue(str(p).startswith(str(Path.home())))

    def test_is_under_true(self):
        self.assertTrue(_is_under(Path("/a/b/c"), Path("/a")))
        self.assertTrue(_is_under(Path("/a/b/c"), Path("/a/b")))

    def test_is_under_false(self):
        self.assertFalse(_is_under(Path("/a/b/c"), Path("/a/b/d")))
        self.assertFalse(_is_under(Path("/x"), Path("/a")))


if __name__ == "__main__":
    unittest.main()