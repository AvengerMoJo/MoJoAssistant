"""
Test Scheduler Implementation

Quick test to verify scheduler core functionality works correctly.
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.scheduler.core import Scheduler
from app.scheduler.models import Task, TaskType, TaskPriority, TaskStatus
from app.scheduler.triggers import create_daily_trigger, parse_cron_expression


async def test_basic_scheduler():
    """Test basic scheduler operations"""
    print("=" * 70)
    print("Testing Scheduler Foundation")
    print("=" * 70)

    # Use test storage path
    storage_path = "/tmp/test_scheduler_tasks.json"

    # Create scheduler (don't start ticker yet)
    scheduler = Scheduler(storage_path=storage_path, tick_interval=2)

    print("\n1️⃣ Testing Task Creation")
    print("-" * 70)

    # Create immediate test task
    task1 = Task(
        id="test_task_1",
        type=TaskType.CUSTOM,
        priority=TaskPriority.HIGH,
        config={"command": "echo 'Hello from scheduler!'"},
        description="Test immediate execution"
    )

    # Create scheduled task (5 seconds from now)
    task2 = Task(
        id="test_task_2",
        type=TaskType.CUSTOM,
        schedule=datetime.now() + timedelta(seconds=5),
        priority=TaskPriority.MEDIUM,
        config={"command": "echo 'Scheduled task executed'"},
        description="Test scheduled execution"
    )

    # Add tasks
    success1 = scheduler.add_task(task1)
    success2 = scheduler.add_task(task2)

    print(f"   Task 1 added: {success1}")
    print(f"   Task 2 added: {success2}")

    print("\n2️⃣ Testing Task Queue")
    print("-" * 70)

    # List tasks
    tasks = scheduler.list_tasks()
    print(f"   Total tasks in queue: {len(tasks)}")
    for task in tasks:
        print(f"   - {task.id}: {task.type.value} ({task.priority.value}) - {task.status.value}")

    print("\n3️⃣ Testing Scheduler Status")
    print("-" * 70)

    status = scheduler.get_status()
    print(f"   Running: {status['running']}")
    print(f"   Tick count: {status['tick_count']}")
    print(f"   Queue: {status['queue']['total']} tasks")
    print(f"   By status: {status['queue']['by_status']}")

    print("\n4️⃣ Testing Ticker Loop (10 seconds)")
    print("-" * 70)
    print("   Starting scheduler...")

    # Run scheduler for 10 seconds
    async def run_scheduler():
        await asyncio.sleep(10)
        scheduler.stop()

    # Start both tasks concurrently
    await asyncio.gather(
        scheduler.start(),
        run_scheduler()
    )

    print("\n5️⃣ Final Results")
    print("-" * 70)

    # Check task status
    task1_result = scheduler.get_task("test_task_1")
    task2_result = scheduler.get_task("test_task_2")

    if task1_result:
        print(f"   Task 1 status: {task1_result.status.value}")
        if task1_result.result:
            print(f"   Task 1 success: {task1_result.result.success}")

    if task2_result:
        print(f"   Task 2 status: {task2_result.status.value}")
        if task2_result.result:
            print(f"   Task 2 success: {task2_result.result.success}")

    final_status = scheduler.get_status()
    print(f"\n   Final statistics:")
    print(f"   - Total ticks: {final_status['tick_count']}")
    print(f"   - Tasks executed: {final_status['statistics']['tasks_executed']}")
    print(f"   - Tasks succeeded: {final_status['statistics']['tasks_succeeded']}")
    print(f"   - Tasks failed: {final_status['statistics']['tasks_failed']}")

    print("\n✅ Scheduler test completed successfully!")


def test_cron_triggers():
    """Test cron trigger parsing"""
    print("\n" + "=" * 70)
    print("Testing Cron Triggers")
    print("=" * 70)

    # Test daily 3 AM trigger
    trigger = create_daily_trigger(3, 0)
    print(f"\n   Daily 3 AM trigger: {trigger.expression}")

    # Calculate next run
    now = datetime.now()
    next_run = trigger.get_next_run_time(now)
    print(f"   Next run: {next_run}")
    print(f"   In: {(next_run - now).total_seconds() / 3600:.1f} hours")

    # Test custom cron expression
    print("\n   Testing cron expressions:")
    expressions = [
        ("0 3 * * *", "Every day at 3:00 AM"),
        ("30 14 * * 1-5", "Weekdays at 2:30 PM"),
        ("0 */6 * * *", "Every 6 hours"),
        ("15 0 1 * *", "First day of month at 12:15 AM"),
    ]

    for expr, description in expressions:
        try:
            cron = parse_cron_expression(expr)
            next_time = cron.get_next_run_time(now)
            hours_until = (next_time - now).total_seconds() / 3600
            print(f"   ✓ {expr:20s} - {description:30s} (in {hours_until:.1f}h)")
        except Exception as e:
            print(f"   ✗ {expr:20s} - Error: {e}")

    print("\n✅ Cron trigger tests completed!")


def main():
    """Run all tests"""
    print("\n🧪 Scheduler Foundation Tests\n")

    # Test cron triggers first (synchronous)
    test_cron_triggers()

    # Test scheduler (async)
    asyncio.run(test_basic_scheduler())

    print("\n" + "=" * 70)
    print("All tests completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()
