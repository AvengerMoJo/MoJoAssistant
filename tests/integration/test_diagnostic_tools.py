"""
Diagnostic Tools Integration Test

Tests diagnostic and cleanup actions via unified agent_action tool:
- detect_duplicates: Find duplicate projects (same git_url)
- cleanup_orphaned: Clean up orphaned processes

Usage:
    python tests/integration/test_diagnostic_tools.py
"""

import asyncio
import sys
from pathlib import Path
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.mcp.core.tools import ToolRegistry


class MockMemoryService:
    """Minimal mock memory service for testing"""

    def __init__(self):
        pass

    def get_context(self, *args, **kwargs):
        return {"context": "", "sources": []}

    def add_memory(self, *args, **kwargs):
        return {"success": True}

    def search(self, *args, **kwargs):
        return []


@pytest.mark.asyncio
async def test_detect_duplicates():
    """Test duplicate detection via agent_action"""
    print("\n" + "="*70)
    print("  Test: Detect Duplicate Projects")
    print("="*70 + "\n")

    tools = ToolRegistry(MockMemoryService())

    print("Running duplicate detection...")
    result = await tools.execute("agent_action", {
        "agent_type": "opencode",
        "action": "detect_duplicates",
    })

    if result.get("status") == "success":
        print(f"[+] Detection completed successfully\n")
        print(f"Total projects: {result.get('total_projects', 0)}")
        print(f"Unique repositories: {result.get('unique_repositories', 0)}")
        print(f"Duplicates found: {result.get('duplicates_found', 0)}")

        duplicates = result.get("duplicates", [])
        if duplicates:
            print("\n  Duplicate Details:\n")
            for dup in duplicates:
                print(f"Repository: {dup['git_url']}")
                print(f"  Count: {dup['count']} instances")
                print(f"  Recommendation: Keep '{dup['recommended_to_keep']}'")
                print(f"  ({dup['recommendation']})\n")

                print("  Instances:")
                for instance in dup['instances']:
                    status = "Running" if instance['opencode_running'] else "Stopped"
                    print(f"    {status} - {instance['project_name']}")
                    print(f"      Base dir: {instance['base_dir']}")
                    print(f"      Port: {instance['opencode_port']}")
                print()
        else:
            print(f"\n[+] {result.get('message', 'No duplicates found')}")

        return True
    else:
        print(f"[FAIL] Detection failed: {result.get('message')}")
        return False


@pytest.mark.asyncio
async def test_cleanup_orphaned():
    """Test orphaned process cleanup via agent_action"""
    print("\n" + "="*70)
    print("  Test: Clean Up Orphaned Processes")
    print("="*70 + "\n")

    tools = ToolRegistry(MockMemoryService())

    print("Running orphaned process cleanup...")
    result = await tools.execute("agent_action", {
        "agent_type": "opencode",
        "action": "cleanup_orphaned",
    })

    if result.get("status") == "success":
        print(f"[+] Cleanup completed successfully\n")
        print(f"Orphaned processes found: {result.get('orphaned_count', 0)}")
        print(f"Cleaned up: {result.get('cleaned_count', 0)}")

        orphaned = result.get("orphaned_processes", [])
        if orphaned:
            print("\n  Cleaned Up Processes:\n")
            for process in orphaned:
                print(f"  Project: {process['project']}")
                print(f"    PID: {process['pid']}")
                print(f"    Reason: {process['reason']}")
                print()

            cleaned = result.get("cleaned_projects", [])
            if cleaned:
                print(f"[+] Successfully cleaned: {', '.join(cleaned)}")
        else:
            print(f"\n[+] {result.get('message', 'No orphaned processes found')}")

        return True
    else:
        print(f"[FAIL] Cleanup failed: {result.get('message')}")
        return False


@pytest.mark.asyncio
async def test_all_diagnostic_tools():
    """Run all diagnostic tool tests"""
    print("\n" + "="*70)
    print("  Agent Manager - Diagnostic Tools Integration Test")
    print("="*70)

    results = []

    # Test 1: Detect duplicates
    try:
        success = await test_detect_duplicates()
        results.append(("Detect Duplicates", success))
    except Exception as e:
        print(f"\n[FAIL] Exception in detect duplicates: {str(e)}")
        import traceback
        traceback.print_exc()
        results.append(("Detect Duplicates", False))

    # Test 2: Cleanup orphaned
    try:
        success = await test_cleanup_orphaned()
        results.append(("Cleanup Orphaned", success))
    except Exception as e:
        print(f"\n[FAIL] Exception in cleanup orphaned: {str(e)}")
        import traceback
        traceback.print_exc()
        results.append(("Cleanup Orphaned", False))

    # Print summary
    print("\n" + "="*70)
    print("  Test Summary")
    print("="*70 + "\n")

    passed = sum(1 for _, success in results if success)
    total = len(results)

    print(f"Results: {passed}/{total} tests passed\n")

    for name, success in results:
        symbol = "[+]" if success else "[FAIL]"
        print(f"{symbol} {name}")

    print("\n" + "="*70)

    if passed == total:
        print("ALL TESTS PASSED!")
    else:
        print(f"{total - passed} test(s) failed")

    print("="*70 + "\n")

    return passed == total


async def main():
    """Main entry point"""
    try:
        success = await test_all_diagnostic_tools()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n  Test interrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
