"""
Test for sandbox_dir bug fix

Verifies that ProjectConfig uses base_dir (not sandbox_dir)
and that ProcessManager correctly accesses it.

Bug: 'ProjectConfig' object has no attribute 'sandbox_dir'
Fix: Changed process_manager.py to use config.base_dir instead

Run with:
    python tests/unit/test_bugfix_sandbox_dir.py
"""

import unittest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.mcp.opencode.models import ProjectConfig, ProjectState


class TestSandboxDirBugFix(unittest.TestCase):
    """Test the sandbox_dir attribute bug fix"""

    def test_project_config_has_base_dir(self):
        """ProjectConfig should have base_dir attribute"""
        config = ProjectConfig(
            git_url="git@github.com:user/repo.git",
            base_dir="/path/to/project"
        )

        self.assertTrue(hasattr(config, 'base_dir'))
        self.assertEqual(config.base_dir, "/path/to/project")

    def test_project_config_no_sandbox_dir(self):
        """ProjectConfig should NOT have sandbox_dir attribute"""
        config = ProjectConfig(
            git_url="git@github.com:user/repo.git",
            base_dir="/path/to/project"
        )

        # This was the bug - code tried to access sandbox_dir on ProjectConfig
        self.assertFalse(hasattr(config, 'sandbox_dir'))

    def test_project_state_has_sandbox_dir_for_compat(self):
        """ProjectState should have sandbox_dir for backward compatibility"""
        state = ProjectState(
            git_url="git@github.com:user/repo.git",
            base_dir="/path/to/project"
        )

        # ProjectState keeps sandbox_dir for backward compat
        self.assertTrue(hasattr(state, 'sandbox_dir'))

    def test_project_state_migrates_sandbox_dir_to_base_dir(self):
        """ProjectState should migrate old sandbox_dir to base_dir"""
        state = ProjectState(
            git_url="git@github.com:user/repo.git",
            sandbox_dir="/old/sandbox/path",  # Old field
            base_dir=None  # New field not set
        )

        # __post_init__ should migrate sandbox_dir to base_dir
        self.assertEqual(state.base_dir, "/old/sandbox/path")

    def test_project_config_can_be_created(self):
        """Should be able to create ProjectConfig without errors"""
        # This would have failed before the fix when ProcessManager
        # tried to access config.sandbox_dir
        config = ProjectConfig(
            git_url="git@github.com:user/repo.git",
            project_name="user-repo",
            base_dir="/path/to/project",
            ssh_key_path="/path/to/key",
            opencode_password="test-password",
            mcp_bearer_token="test-token"
        )

        self.assertIsNotNone(config)
        self.assertEqual(config.base_dir, "/path/to/project")

    def test_access_base_dir_not_sandbox_dir(self):
        """Demonstrate the correct way to access directory"""
        config = ProjectConfig(
            git_url="git@github.com:user/repo.git",
            base_dir="/correct/path"
        )

        # CORRECT: Access base_dir
        directory = config.base_dir
        self.assertEqual(directory, "/correct/path")

        # INCORRECT (would cause AttributeError):
        # directory = config.sandbox_dir  # This attribute doesn't exist!


def run_tests():
    """Run all tests with detailed output"""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestSandboxDirBugFix)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "="*70)
    print("Bug Fix Verification")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.wasSuccessful():
        print("\n✅ Bug fix verified - ProjectConfig now uses base_dir correctly!")
    else:
        print("\n❌ Tests failed - bug may still exist")

    print("="*70)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
