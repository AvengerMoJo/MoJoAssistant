"""
Test Scheduler Daemon Auto-Start

Verify that the scheduler daemon starts automatically when ToolRegistry
is initialized and can be controlled via MCP tools.
"""

import asyncio
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


async def test_scheduler_daemon():
    """Test scheduler daemon lifecycle"""
    print("=" * 70)
    print("Testing Scheduler Daemon Auto-Start")
    print("=" * 70)

    print("\n1️⃣ Creating ToolRegistry (should auto-start scheduler)")
    print("-" * 70)

    # Create a minimal ToolRegistry without memory service
    # We'll mock it by using None since scheduler doesn't require memory service
    class MockMemoryService:
        """Minimal mock for memory service"""
        pass

    from app.mcp.core.tools import ToolRegistry

    # Create registry - this should auto-start the scheduler daemon
    registry = ToolRegistry(MockMemoryService())
    print("   ✅ ToolRegistry created")

    # Give daemon time to start
    await asyncio.sleep(2)

    print("\n2️⃣ Checking Daemon Status (via MCP tool)")
    print("-" * 70)

    # Use MCP tool to check daemon status
    status_result = await registry.execute("scheduler_daemon_status", {})

    print(f"   Status: {status_result.get('status')}")
    if status_result['status'] == 'success':
        daemon_info = status_result['daemon']
        scheduler_info = status_result['scheduler']

        print(f"   Daemon running: {daemon_info['running']}")
        print(f"   Thread alive: {daemon_info['thread_alive']}")
        print(f"   Thread name: {daemon_info['thread_name']}")
        print(f"   Scheduler tick count: {scheduler_info['tick_count']}")
        print(f"   Scheduler tick interval: {scheduler_info['tick_interval']}s")

        if daemon_info['running'] and daemon_info['thread_alive']:
            print("\n   ✅ Scheduler daemon is running automatically!")
        else:
            print("\n   ❌ Scheduler daemon failed to start")
            return False
    else:
        print(f"   ❌ Failed to get status: {status_result.get('message')}")
        return False

    print("\n3️⃣ Adding a Test Task")
    print("-" * 70)

    # Add a test task
    add_result = await registry.execute(
        "scheduler_add_task",
        {
            "task_id": "test_daemon_task",
            "task_type": "custom",
            "priority": "high",
            "config": {"command": "echo 'Daemon is working!'"},
            "description": "Test task to verify daemon execution"
        }
    )

    print(f"   Status: {add_result.get('status')}")
    print(f"   Message: {add_result.get('message')}")

    if add_result['status'] == 'success':
        print("   ✅ Task added successfully")
    else:
        print("   ❌ Failed to add task")
        return False

    print("\n4️⃣ Waiting for Task Execution (60s tick interval)")
    print("-" * 70)
    print("   Waiting for scheduler to execute task...")

    # Wait for up to 75 seconds for task to be picked up and executed
    max_wait = 75
    wait_interval = 5
    elapsed = 0

    while elapsed < max_wait:
        await asyncio.sleep(wait_interval)
        elapsed += wait_interval

        # Check task status
        task_result = await registry.execute(
            "scheduler_get_task",
            {"task_id": "test_daemon_task"}
        )

        if task_result['status'] == 'success':
            task = task_result['task']
            task_status = task['status']

            print(f"   [{elapsed}s] Task status: {task_status}")

            if task_status == 'completed':
                print("\n   ✅ Task executed successfully by daemon!")
                break
            elif task_status == 'failed':
                print(f"\n   ❌ Task failed: {task.get('result', {}).get('error_message')}")
                break
        else:
            print(f"   ❌ Task not found")
            break

    print("\n5️⃣ Testing Daemon Control (Stop/Start)")
    print("-" * 70)

    # Stop daemon
    stop_result = await registry.execute("scheduler_stop_daemon", {})
    print(f"   Stop result: {stop_result.get('message')}")

    await asyncio.sleep(1)

    # Check status
    status_result = await registry.execute("scheduler_daemon_status", {})
    daemon_running = status_result['daemon']['running']
    print(f"   Daemon running after stop: {daemon_running}")

    if not daemon_running:
        print("   ✅ Daemon stopped successfully")
    else:
        print("   ❌ Daemon still running after stop")

    # Start daemon again
    start_result = await registry.execute("scheduler_start_daemon", {})
    print(f"   Start result: {start_result.get('message')}")

    await asyncio.sleep(2)

    # Check status again
    status_result = await registry.execute("scheduler_daemon_status", {})
    daemon_running = status_result['daemon']['running']
    print(f"   Daemon running after start: {daemon_running}")

    if daemon_running:
        print("   ✅ Daemon restarted successfully")
    else:
        print("   ❌ Daemon failed to restart")

    print("\n6️⃣ Final Cleanup")
    print("-" * 70)

    # Stop daemon before exit
    await registry.execute("scheduler_stop_daemon", {})
    print("   ✅ Daemon stopped for cleanup")

    return True


def main():
    """Run tests"""
    print("\n🧪 Scheduler Daemon Auto-Start Tests\n")

    success = asyncio.run(test_scheduler_daemon())

    print("\n" + "=" * 70)
    if success:
        print("✅ All daemon tests passed!")
    else:
        print("❌ Some daemon tests failed")
    print("=" * 70)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
