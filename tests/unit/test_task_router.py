"""Tests for task router."""

import pytest
from app.scheduler.task_router import compute_cell, TaskRouter, RoutingResult


class TestComputeCell:
    def test_single_file_tool(self):
        assert compute_cell("What is the version?", ["read_file"]) == "A"

    def test_file_plus_write(self):
        # write_file is HIGH_AC (adds breadth) and state tool (adds depth) → D
        assert compute_cell("Read and write the result", ["read_file", "write_file"]) == "D"

    def test_multiple_independent_tools(self):
        assert compute_cell("Get info from multiple sources", ["read_file", "list_files", "web_search"]) == "C"

    def test_multi_tool_with_dependency(self):
        assert compute_cell("Read config then write result based on findings", ["read_file", "write_file", "bash_exec"]) == "D"

    def test_empty_tools(self):
        assert compute_cell("Simple question", []) == "A"

    def test_single_code_tool(self):
        # bash_exec is HIGH_AC (adds breadth) and state tool (adds depth) → D
        assert compute_cell("Run a command", ["bash_exec"]) == "D"


class TestTaskRouter:
    def test_classify_and_route(self):
        router = TaskRouter(routing_table={
            "A": "model_a",
            "B": "model_b",
            "C": "model_c",
            "D": "model_d",
        })
        result = router.classify_and_route(
            goal="What is the version?",
            role_id="test",
            declared_tools=["read_file"],
        )
        assert result["cell"] == "A"
        assert result["model_id"] == "model_a"
        assert "confidence" in result
        assert "explain" in result

    def test_validate_tool_call_valid(self):
        router = TaskRouter(routing_table={})
        valid, reason = router.validate_tool_call(
            {"function": {"name": "read_file"}},
            ["read_file", "write_file"],
        )
        assert valid is True

    def test_validate_tool_call_invalid(self):
        router = TaskRouter(routing_table={})
        valid, reason = router.validate_tool_call(
            {"function": {"name": "bash_exec"}},
            ["read_file", "write_file"],
        )
        assert valid is False
        assert "not in role" in reason

    def test_should_escalate_loop(self):
        router = TaskRouter(routing_table={})
        trace = [
            {"tool_name": "read_file", "args": {"path": "/test"}},
            {"tool_name": "read_file", "args": {"path": "/test"}},
        ]
        escalate, reason = router.should_escalate(trace)
        assert escalate is True
        assert "Loop" in reason

    def test_should_escalate_errors(self):
        router = TaskRouter(routing_table={})
        trace = [
            {"tool_name": "read_file", "error": "not found"},
            {"tool_name": "read_file", "error": "not found"},
            {"tool_name": "read_file", "error": "not found"},
        ]
        escalate, reason = router.should_escalate(trace)
        assert escalate is True

    def test_should_not_escalate_normal(self):
        router = TaskRouter(routing_table={})
        trace = [
            {"tool_name": "read_file", "args": {"path": "/a"}},
            {"tool_name": "write_file", "args": {"path": "/b"}},
        ]
        escalate, reason = router.should_escalate(trace)
        assert escalate is False
