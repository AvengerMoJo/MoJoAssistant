"""
Complete Workflow Integration Test

Tests the entire Agent Manager workflow using unified agent_* tools:
1. Start a project (agent_start)
2. Get deploy key (agent_action)
3. List projects (agent_list)
4. Get project status (agent_status)
5. Create a sandbox/worktree (agent_action)
6. List sandboxes (agent_action)
7. Cleanup (delete sandbox, stop project)

Run this test with a real git repository to validate end-to-end functionality.

Usage:
    python tests/integration/test_complete_workflow.py
    python tests/integration/test_complete_workflow.py --git-url git@github.com:user/repo.git
"""

import asyncio
import sys
import argparse
from pathlib import Path

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


class WorkflowTester:
    """Integration test for complete agent workflow"""

    def __init__(self, git_url: str):
        self.git_url = git_url
        self.memory_service = MockMemoryService()
        self.tools = ToolRegistry(self.memory_service)
        self.project_started = False
        self.sandbox_created = False
        self.sandbox_name = None

    def print_section(self, title: str):
        """Print section header"""
        print(f"\n{'='*70}")
        print(f"  {title}")
        print(f"{'='*70}\n")

    def print_result(self, step: str, result: dict):
        """Print step result"""
        status = result.get("status", "unknown")
        symbol = "+" if status == "success" else "FAIL"
        print(f"[{symbol}] {step}")

        if status == "error":
            print(f"   Error: {result.get('message', 'Unknown error')}")
        else:
            for key in ["project", "git_url", "opencode_port", "base_dir", "message"]:
                if key in result:
                    print(f"   {key}: {result[key]}")

    async def test_01_start_project(self):
        """Test: Start project via agent_start"""
        self.print_section("Step 1: Start Project")

        print(f"Starting project for: {self.git_url}")
        result = await self.tools.execute("agent_start", {
            "agent_type": "opencode",
            "identifier": self.git_url,
        })

        self.print_result("Start Project", result)

        if result.get("status") == "success":
            self.project_started = True
            self.opencode_port = result.get("opencode_port")
            self.project_name = result.get("project")
            return True
        return False

    async def test_02_get_deploy_key(self):
        """Test: Get SSH deploy key via agent_action"""
        self.print_section("Step 2: Get Deploy Key")

        print("Retrieving SSH deploy key...")
        result = await self.tools.execute("agent_action", {
            "agent_type": "opencode",
            "action": "get_deploy_key",
            "params": {"git_url": self.git_url},
        })

        self.print_result("Get Deploy Key", result)

        if result.get("status") == "success":
            print(f"\n  Public Key:")
            print("-" * 70)
            print(result.get("public_key", "N/A"))
            print("-" * 70)

            if result.get("github_deploy_keys_url"):
                print(f"\n  Add key at: {result['github_deploy_keys_url']}")

            return True
        return False

    async def test_03_list_projects(self):
        """Test: List all projects via agent_list"""
        self.print_section("Step 3: List Projects")

        print("Listing all projects...")
        result = await self.tools.execute("agent_list", {
            "agent_type": "opencode",
        })

        if result.get("status") == "success":
            projects = result.get("projects", [])
            print(f"[+] Found {len(projects)} project(s)")

            for proj in projects:
                print(f"\n   Project: {proj.get('name')}")
                print(f"   Git URL: {proj.get('git_url')}")
                print(f"   Port: {proj.get('opencode_port', 'N/A')}")
                print(f"   Running: {proj.get('opencode_running', False)}")
                print(f"   Base Dir: {proj.get('base_dir', 'N/A')}")

            return True
        else:
            print(f"[FAIL] Failed to list projects: {result.get('message')}")
            return False

    async def test_04_project_status(self):
        """Test: Get project status via agent_status"""
        self.print_section("Step 4: Get Project Status")

        print(f"Getting status for: {self.git_url}")
        result = await self.tools.execute("agent_status", {
            "agent_type": "opencode",
            "identifier": self.git_url,
        })

        self.print_result("Project Status", result)

        if result.get("status") == "success":
            opencode = result.get("opencode", {})
            print(f"\n   OpenCode Process:")
            print(f"   - PID: {opencode.get('pid', 'N/A')}")
            print(f"   - Port: {opencode.get('port', 'N/A')}")
            print(f"   - Running: {opencode.get('running', False)}")

            return True
        return False

    async def test_05_create_sandbox(self):
        """Test: Create sandbox/worktree via agent_action"""
        self.print_section("Step 5: Create Sandbox")

        sandbox_name = "test-sandbox"
        print(f"Creating sandbox: {sandbox_name}")

        result = await self.tools.execute("agent_action", {
            "agent_type": "opencode",
            "action": "sandbox_create",
            "params": {
                "git_url": self.git_url,
                "name": sandbox_name,
            },
        })

        self.print_result("Create Sandbox", result)

        if result.get("status") == "success":
            self.sandbox_created = True
            self.sandbox_name = sandbox_name

            worktree = result.get("worktree", {})
            print(f"\n   Worktree Details:")
            print(f"   - Name: {worktree.get('name', 'N/A')}")
            print(f"   - Branch: {worktree.get('branch', 'N/A')}")
            print(f"   - Directory: {worktree.get('directory', 'N/A')}")

            return True
        return False

    async def test_06_list_sandboxes(self):
        """Test: List all sandboxes via agent_action"""
        self.print_section("Step 6: List Sandboxes")

        print(f"Listing sandboxes for: {self.git_url}")
        result = await self.tools.execute("agent_action", {
            "agent_type": "opencode",
            "action": "sandbox_list",
            "params": {"git_url": self.git_url},
        })

        if result.get("status") == "success":
            worktrees = result.get("worktrees", [])
            count = result.get("count", 0)

            print(f"[+] Found {count} worktree(s)")

            for wt in worktrees:
                print(f"\n   Worktree:")
                print(f"   - Name: {wt.get('name', 'N/A')}")
                print(f"   - Path: {wt.get('path', 'N/A')}")
                print(f"   - Branch: {wt.get('branch', 'N/A')}")

            return True
        else:
            print(f"[FAIL] Failed to list sandboxes: {result.get('message')}")
            return False

    async def cleanup_10_delete_sandbox(self):
        """Cleanup: Delete the sandbox"""
        self.print_section("Cleanup: Delete Sandbox")

        if not self.sandbox_created:
            print("  No sandbox to delete")
            return True

        print(f"Deleting sandbox: {self.sandbox_name}")
        result = await self.tools.execute("agent_action", {
            "agent_type": "opencode",
            "action": "sandbox_delete",
            "params": {
                "git_url": self.git_url,
                "name": self.sandbox_name,
            },
        })

        self.print_result("Delete Sandbox", result)
        return result.get("status") == "success"

    async def cleanup_11_stop_project(self):
        """Cleanup: Stop the project"""
        self.print_section("Cleanup: Stop Project")

        if not self.project_started:
            print("  No project to stop")
            return True

        print(f"Stopping project: {self.git_url}")
        result = await self.tools.execute("agent_stop", {
            "agent_type": "opencode",
            "identifier": self.git_url,
        })

        self.print_result("Stop Project", result)
        return result.get("status") == "success"

    async def run_all_tests(self):
        """Run complete workflow test"""
        print("\n" + "="*70)
        print("  Agent Manager - Complete Workflow Integration Test")
        print("="*70)
        print(f"\nGit URL: {self.git_url}")

        tests = [
            ("Start Project", self.test_01_start_project),
            ("Get Deploy Key", self.test_02_get_deploy_key),
            ("List Projects", self.test_03_list_projects),
            ("Project Status", self.test_04_project_status),
            ("Create Sandbox", self.test_05_create_sandbox),
            ("List Sandboxes", self.test_06_list_sandboxes),
        ]

        cleanup_tests = [
            ("Delete Sandbox", self.cleanup_10_delete_sandbox),
            ("Stop Project", self.cleanup_11_stop_project),
        ]

        results = []

        # Run main tests
        for name, test_func in tests:
            try:
                success = await test_func()
                results.append((name, success))

                # Stop if critical step fails
                if not success and name in ["Start Project", "Create Sandbox"]:
                    print(f"\n  Critical test failed: {name}")
                    print("Skipping remaining tests and proceeding to cleanup...")
                    break

            except Exception as e:
                print(f"\n[FAIL] Exception in {name}: {str(e)}")
                import traceback
                traceback.print_exc()
                results.append((name, False))
                break

        # Always run cleanup
        print("\n" + "="*70)
        print("  CLEANUP")
        print("="*70)

        for name, cleanup_func in cleanup_tests:
            try:
                await cleanup_func()
            except Exception as e:
                print(f"\n  Cleanup error in {name}: {str(e)}")

        # Print summary
        self.print_section("Test Summary")

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
    parser = argparse.ArgumentParser(description="Agent Manager Complete Workflow Test")
    parser.add_argument(
        "--git-url",
        type=str,
        default="https://github.com:anthropics/anthropic-quickstarts.git",
        help="Git repository URL to test with (default: anthropic-quickstarts)"
    )
    parser.add_argument(
        "--skip-ssh-check",
        action="store_true",
        help="Skip SSH key validation (test will fail at clone step if key not added)"
    )

    args = parser.parse_args()

    tester = WorkflowTester(args.git_url)

    try:
        success = await tester.run_all_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n  Test interrupted by user")
        print("Running cleanup...")

        try:
            await tester.cleanup_10_delete_sandbox()
            await tester.cleanup_11_stop_project()
        except:
            pass

        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
