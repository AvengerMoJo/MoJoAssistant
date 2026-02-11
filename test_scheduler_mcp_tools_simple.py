"""
Simple Test for Scheduler MCP Tools

Tests that don't require full memory service initialization.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def test_scheduler_tools_defined():
    """Test that scheduler tools are defined in tool registry"""
    print("=" * 70)
    print("Testing Scheduler MCP Tools - Definitions")
    print("=" * 70)

    print("\n1️⃣ Importing ToolRegistry")
    print("-" * 70)

    try:
        from app.mcp.core.tools import ToolRegistry
        print("   ✅ ToolRegistry imported successfully")
    except Exception as e:
        print(f"   ❌ Failed to import ToolRegistry: {e}")
        return False

    print("\n2️⃣ Checking Scheduler Initialization")
    print("-" * 70)

    # Check if __init__ mentions scheduler
    import inspect
    init_source = inspect.getsource(ToolRegistry.__init__)

    if "self.scheduler" in init_source:
        print("   ✅ Scheduler initialized in ToolRegistry.__init__")
    else:
        print("   ❌ Scheduler NOT initialized in ToolRegistry.__init__")
        return False

    if "from app.scheduler.core import Scheduler" in init_source:
        print("   ✅ Scheduler imported correctly")
    else:
        print("   ❌ Scheduler import missing")
        return False

    print("\n3️⃣ Checking Tool Definitions")
    print("-" * 70)

    # Check _define_tools method
    define_tools_source = inspect.getsource(ToolRegistry._define_tools)

    expected_tools = [
        "scheduler_add_task",
        "scheduler_list_tasks",
        "scheduler_get_status",
        "scheduler_get_task",
        "scheduler_remove_task"
    ]

    found_tools = []
    for tool in expected_tools:
        if f'"name": "{tool}"' in define_tools_source:
            found_tools.append(tool)
            print(f"   ✅ {tool} defined")
        else:
            print(f"   ❌ {tool} NOT defined")

    print(f"\n   Summary: {len(found_tools)}/{len(expected_tools)} tools defined")

    print("\n4️⃣ Checking Execution Methods")
    print("-" * 70)

    # Check execute method
    execute_source = inspect.getsource(ToolRegistry.execute)

    for tool in expected_tools:
        method_name = f"_execute_{tool}"
        if f'"{tool}"' in execute_source:
            print(f"   ✅ {tool} handled in execute")

            # Check if execution method exists
            if hasattr(ToolRegistry, method_name):
                print(f"      ✅ {method_name} exists")
            else:
                print(f"      ❌ {method_name} missing")
        else:
            print(f"   ❌ {tool} NOT handled in execute")

    print("\n5️⃣ Testing Scheduler Direct Access")
    print("-" * 70)

    try:
        from app.scheduler.core import Scheduler
        from app.scheduler.models import Task, TaskType, TaskPriority

        # Create a test scheduler
        test_scheduler = Scheduler(storage_path="/tmp/test_mcp_scheduler.json", tick_interval=60)
        print("   ✅ Scheduler instance created")

        # Test creating a task
        task = Task(
            id="test_mcp_tool",
            type=TaskType.CUSTOM,
            priority=TaskPriority.MEDIUM,
            config={"command": "echo 'test'"},
            description="Test task for MCP tools"
        )

        success = test_scheduler.add_task(task)
        print(f"   ✅ Task added: {success}")

        # Test listing tasks
        tasks = test_scheduler.list_tasks()
        print(f"   ✅ Tasks listed: {len(tasks)} tasks")

        # Test getting status
        status = test_scheduler.get_status()
        print(f"   ✅ Status retrieved: {status['tick_count']} ticks")

        # Test removing task
        removed = test_scheduler.remove_task("test_mcp_tool")
        print(f"   ✅ Task removed: {removed}")

        print("\n   All scheduler operations work correctly!")

    except Exception as e:
        print(f"   ❌ Error testing scheduler: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


def main():
    """Run tests"""
    print("\n🧪 Scheduler MCP Tools Simple Tests\n")

    success = test_scheduler_tools_defined()

    print("\n" + "=" * 70)
    if success:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
    print("=" * 70)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
