"""
Test Scheduler MCP Tools

Verify the scheduler MCP tool integration works correctly.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.mcp.core.tools import ToolRegistry
from app.services.hybrid_memory_service import HybridMemoryService


async def test_scheduler_mcp_tools():
    """Test scheduler MCP tools"""
    print("=" * 70)
    print("Testing Scheduler MCP Tools")
    print("=" * 70)

    # Initialize tool registry with memory service
    print("\n1️⃣ Initializing Tool Registry")
    print("-" * 70)

    memory_service = HybridMemoryService()
    registry = ToolRegistry(memory_service)

    print("   ✅ Tool registry initialized")
    print(f"   Total tools: {len(registry.list_tools())}")

    # Check scheduler tools are registered
    all_tools = [tool['name'] for tool in registry.list_tools()]
    scheduler_tools = [tool for tool in all_tools if tool.startswith('scheduler_')]

    print(f"\n   Scheduler tools registered: {len(scheduler_tools)}")
    for tool in scheduler_tools:
        print(f"   - {tool}")

    print("\n2️⃣ Testing scheduler_add_task")
    print("-" * 70)

    # Add a test task
    result = await registry.execute_tool(
        "scheduler_add_task",
        {
            "task_id": "test_mcp_task_1",
            "task_type": "custom",
            "priority": "high",
            "config": {"command": "echo 'Hello from MCP tool!'"},
            "description": "Test task added via MCP tool"
        }
    )

    print(f"   Status: {result.get('status')}")
    print(f"   Message: {result.get('message')}")

    if result['status'] == 'success':
        print(f"   Task ID: {result['task']['id']}")
        print(f"   Task Type: {result['task']['type']}")
        print(f"   Priority: {result['task']['priority']}")

    # Add a scheduled task
    schedule_time = (datetime.now() + timedelta(hours=2)).isoformat()
    result2 = await registry.execute_tool(
        "scheduler_add_task",
        {
            "task_id": "test_scheduled_task",
            "task_type": "dreaming",
            "priority": "medium",
            "schedule": schedule_time,
            "description": "Scheduled dreaming task"
        }
    )

    print(f"\n   Scheduled task added: {result2.get('status')}")

    print("\n3️⃣ Testing scheduler_list_tasks")
    print("-" * 70)

    result = await registry.execute_tool("scheduler_list_tasks", {})

    print(f"   Status: {result.get('status')}")
    print(f"   Total tasks: {result.get('total')}")

    if result['status'] == 'success' and result.get('tasks'):
        for task in result['tasks'][:5]:  # Show first 5
            print(f"\n   Task: {task['id']}")
            print(f"   - Type: {task['type']}")
            print(f"   - Priority: {task['priority']}")
            print(f"   - Status: {task['status']}")
            if task.get('description'):
                print(f"   - Description: {task['description']}")

    print("\n4️⃣ Testing scheduler_get_task")
    print("-" * 70)

    result = await registry.execute_tool(
        "scheduler_get_task",
        {"task_id": "test_mcp_task_1"}
    )

    print(f"   Status: {result.get('status')}")
    if result['status'] == 'success':
        task = result['task']
        print(f"   Task ID: {task['id']}")
        print(f"   Type: {task['type']}")
        print(f"   Priority: {task['priority']}")
        print(f"   Status: {task['status']}")
        print(f"   Created: {task['created_at']}")

    print("\n5️⃣ Testing scheduler_get_status")
    print("-" * 70)

    result = await registry.execute_tool("scheduler_get_status", {})

    print(f"   Status: {result.get('status')}")
    if result['status'] == 'success':
        scheduler = result['scheduler']
        print(f"\n   Scheduler Status:")
        print(f"   - Running: {scheduler['running']}")
        print(f"   - Tick count: {scheduler['tick_count']}")
        print(f"   - Tick interval: {scheduler['tick_interval']}s")
        print(f"\n   Queue Statistics:")
        print(f"   - Total tasks: {scheduler['queue']['total']}")
        print(f"   - By status: {scheduler['queue']['by_status']}")
        print(f"   - By priority: {scheduler['queue']['by_priority']}")

    print("\n6️⃣ Testing scheduler_remove_task")
    print("-" * 70)

    result = await registry.execute_tool(
        "scheduler_remove_task",
        {"task_id": "test_mcp_task_1"}
    )

    print(f"   Status: {result.get('status')}")
    print(f"   Message: {result.get('message')}")

    # Verify it's removed
    result2 = await registry.execute_tool(
        "scheduler_get_task",
        {"task_id": "test_mcp_task_1"}
    )

    print(f"\n   Verification - task still exists: {result2['status'] == 'success'}")

    print("\n7️⃣ Testing with cron expression")
    print("-" * 70)

    result = await registry.execute_tool(
        "scheduler_add_task",
        {
            "task_id": "daily_dreaming_task",
            "task_type": "dreaming",
            "priority": "medium",
            "cron_expression": "0 3 * * *",
            "description": "Daily memory consolidation at 3 AM"
        }
    )

    print(f"   Status: {result.get('status')}")
    print(f"   Message: {result.get('message')}")

    if result['status'] == 'success':
        task = result['task']
        print(f"   Cron: {task.get('cron_expression')}")

    print("\n✅ All MCP tool tests completed!")


def main():
    """Run tests"""
    print("\n🧪 Scheduler MCP Tools Tests\n")

    asyncio.run(test_scheduler_mcp_tools())

    print("\n" + "=" * 70)
    print("All tests completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()
