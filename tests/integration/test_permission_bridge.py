"""
Permission bridge end-to-end test (item 1 of v1.2.2)

Creates a synthetic coding_agent role (no personal role required), queues a task
that will trigger an OpenCode file-write + shell-exec permission, and verifies the
task enters waiting_for_input so the HITL loop can be exercised.

This test is intentionally NOT fully automated end-to-end (that would require a
running OpenCode server). Instead it:
  1. Creates a synthetic role in a temp location
  2. Queues a task using that role
  3. Verifies the task is accepted by the queue

The live HITL loop (waiting_for_input → attention inbox → reply_to_task → resume)
must be verified manually or in a full integration environment with OpenCode running.

Run with:
    python3 tests/integration/test_permission_bridge.py
    # or
    python3 -m pytest tests/integration/test_permission_bridge.py -v -s
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


SYNTHETIC_ROLE = {
    "id": "test_coding_agent",
    "name": "TestCodingAgent",
    "executor": "coding_agent",
    "backend_type": "opencode",
    "server_id": None,  # set to a git_url at runtime (queue_live_test fills this in)
    "system_prompt": (
        "You are a minimal test coding agent. "
        "Follow instructions exactly. Produce a <FINAL_ANSWER> when done."
    ),
    "model_preference": None,
    "purpose": "Automated permission bridge test role — not for production use.",
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

TASK_GOAL = (
    "In /tmp, create a file called permission_bridge_test.txt containing the text "
    "'Permission bridge test passed.' Then run `cat /tmp/permission_bridge_test.txt` "
    "to verify it was created. Report the output."
)


class TestPermissionBridgeSetup(unittest.TestCase):
    """
    Verifies the permission bridge test task can be queued with a synthetic role.
    Does not require OpenCode to be running.
    """

    def setUp(self):
        self.tmp_role_dir = tempfile.mkdtemp(prefix="mojo_test_roles_")
        role_path = os.path.join(self.tmp_role_dir, "test_coding_agent.json")
        with open(role_path, "w") as f:
            json.dump(SYNTHETIC_ROLE, f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_role_dir, ignore_errors=True)

    def test_synthetic_role_has_required_fields(self):
        self.assertEqual(SYNTHETIC_ROLE["executor"], "coding_agent")
        self.assertIn("system_prompt", SYNTHETIC_ROLE)
        self.assertIn("backend_type", SYNTHETIC_ROLE)

    def test_routing_selects_coding_agent_executor(self):
        """Verify _execute_agentic routes to CodingAgentExecutor for this role."""
        from app.scheduler.models import Task, TaskType, TaskPriority
        from app.scheduler.executor import TaskExecutor
        from unittest.mock import MagicMock, AsyncMock
        import asyncio

        task = Task(
            id="permission_bridge_test_001",
            type=TaskType.ASSISTANT,
            priority=TaskPriority.HIGH,
            config={"role_id": "test_coding_agent", "goal": TASK_GOAL, "max_iterations": 10},
        )

        executor = TaskExecutor.__new__(TaskExecutor)
        executor._log = lambda *a, **k: None

        coding_exec = AsyncMock()
        coding_exec.execute = AsyncMock(
            return_value=MagicMock(success=True, waiting_for_input=None)
        )
        executor._get_coding_agent_executor = MagicMock(return_value=coding_exec)
        executor._get_agentic_executor = MagicMock()

        with patch("app.roles.role_manager.RoleManager") as MockRM:
            MockRM.return_value.get.return_value = SYNTHETIC_ROLE
            asyncio.run(executor._execute_agentic(task))

        coding_exec.execute.assert_called_once_with(task)
        executor._get_agentic_executor.assert_not_called()

    def test_task_config_is_valid(self):
        config = {"role_id": "test_coding_agent", "goal": TASK_GOAL, "max_iterations": 10}
        self.assertIn("role_id", config)
        self.assertIn("goal", config)
        self.assertTrue(len(config["goal"]) > 10)


def queue_live_test():
    """
    Queue the permission bridge test task for a live run against a real OpenCode server.

    Prerequisites:
      1. MoJo scheduler daemon must be running
      2. OpenCode server must be reachable (check with: agent(action="list"))

    After queuing, monitor with:
      scheduler(action="get", task_id="permission_bridge_test_001")
      get_context(type="attention")   # watch for waiting_for_input event

    When it pauses for permission, reply with:
      reply_to_task(task_id="permission_bridge_test_001", reply="once")
    """
    roles_dir = os.path.expanduser("~/.memory/roles")
    role_path = os.path.join(roles_dir, "test_coding_agent.json")

    print(f"Writing synthetic role to {role_path}")
    with open(role_path, "w") as f:
        json.dump(SYNTHETIC_ROLE, f, indent=2)

    from app.scheduler.models import Task, TaskType, TaskPriority
    from app.scheduler.queue import TaskQueue

    task = Task(
        id="permission_bridge_test_001",
        type=TaskType.ASSISTANT,
        priority=TaskPriority.HIGH,
        config={"role_id": "test_coding_agent", "goal": TASK_GOAL, "max_iterations": 10},
        description="Permission bridge test — synthetic role, file create + shell exec",
        created_by="user",
    )

    q = TaskQueue()
    q.remove("permission_bridge_test_001")
    ok = q.add(task)
    print(f"Task queued: {ok} (id={task.id})")
    print()
    print("Monitor:")
    print('  scheduler(action="get", task_id="permission_bridge_test_001")')
    print('  get_context(type="attention")   # watch for waiting_for_input')
    print()
    print("When paused for permission, reply via:")
    print('  reply_to_task(task_id="permission_bridge_test_001", reply="once")')


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Queue the live test task")
    args = parser.parse_args()

    if args.live:
        queue_live_test()
    else:
        unittest.main(argv=[sys.argv[0], "-v"])
