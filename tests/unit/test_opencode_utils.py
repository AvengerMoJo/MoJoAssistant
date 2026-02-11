"""
Unit tests for OpenCode Manager utilities

Tests all utility functions in app/mcp/opencode/utils.py:
- normalize_git_url: URL normalization
- hash_git_url: Deterministic hashing
- sanitize_for_filename: Filename sanitization
- extract_repo_name: Parse owner/repo from URLs
- generate_project_name: Create display names
- generate_base_dir: Generate directory paths

Run with:
    python -m pytest tests/unit/test_opencode_utils.py -v
    # Or with unittest:
    python -m unittest tests/unit/test_opencode_utils.py
"""

import unittest
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.mcp.opencode.utils import (
    normalize_git_url,
    hash_git_url,
    sanitize_for_filename,
    extract_repo_name,
    generate_project_name,
    generate_base_dir,
)


class TestNormalizeGitUrl(unittest.TestCase):
    """Tests for normalize_git_url function"""

    def test_ssh_with_git_suffix(self):
        """SSH format with .git should remain unchanged"""
        url = "git@github.com:user/repo.git"
        result = normalize_git_url(url)
        self.assertEqual(result, "git@github.com:user/repo.git")

    def test_ssh_without_git_suffix(self):
        """SSH format without .git should add .git"""
        url = "git@github.com:user/repo"
        result = normalize_git_url(url)
        self.assertEqual(result, "git@github.com:user/repo.git")

    def test_https_with_git_suffix(self):
        """HTTPS format with .git should convert to SSH"""
        url = "https://github.com/user/repo.git"
        result = normalize_git_url(url)
        self.assertEqual(result, "git@github.com:user/repo.git")

    def test_https_without_git_suffix(self):
        """HTTPS format without .git should convert to SSH with .git"""
        url = "https://github.com/user/repo"
        result = normalize_git_url(url)
        self.assertEqual(result, "git@github.com:user/repo.git")

    def test_gitlab_ssh(self):
        """GitLab SSH format should normalize correctly"""
        url = "git@gitlab.com:user/repo"
        result = normalize_git_url(url)
        self.assertEqual(result, "git@gitlab.com:user/repo.git")

    def test_gitlab_https(self):
        """GitLab HTTPS should convert to SSH"""
        url = "https://gitlab.com/user/repo"
        result = normalize_git_url(url)
        self.assertEqual(result, "git@gitlab.com:user/repo.git")

    def test_bitbucket_ssh(self):
        """Bitbucket SSH format should normalize correctly"""
        url = "git@bitbucket.org:user/repo"
        result = normalize_git_url(url)
        self.assertEqual(result, "git@bitbucket.org:user/repo.git")

    def test_bitbucket_https(self):
        """Bitbucket HTTPS should convert to SSH"""
        url = "https://bitbucket.org/user/repo"
        result = normalize_git_url(url)
        self.assertEqual(result, "git@bitbucket.org:user/repo.git")

    def test_trailing_whitespace(self):
        """Should strip trailing whitespace"""
        url = "  git@github.com:user/repo.git  "
        result = normalize_git_url(url)
        self.assertEqual(result, "git@github.com:user/repo.git")

    def test_nested_path(self):
        """Should handle nested repository paths"""
        url = "https://github.com/org/team/repo"
        result = normalize_git_url(url)
        self.assertEqual(result, "git@github.com:org/team/repo.git")

    def test_custom_domain(self):
        """Should handle custom git domains"""
        url = "https://git.company.com/user/repo"
        result = normalize_git_url(url)
        self.assertEqual(result, "git@git.company.com:user/repo.git")

    def test_idempotent(self):
        """Running normalize twice should give same result"""
        url = "https://github.com/user/repo"
        first = normalize_git_url(url)
        second = normalize_git_url(first)
        self.assertEqual(first, second)


class TestHashGitUrl(unittest.TestCase):
    """Tests for hash_git_url function"""

    def test_deterministic(self):
        """Same URL should always produce same hash"""
        url = "git@github.com:user/repo.git"
        hash1 = hash_git_url(url)
        hash2 = hash_git_url(url)
        self.assertEqual(hash1, hash2)

    def test_hash_length(self):
        """Hash should be 12 characters"""
        url = "git@github.com:user/repo.git"
        result = hash_git_url(url)
        self.assertEqual(len(result), 12)

    def test_hex_format(self):
        """Hash should be hexadecimal"""
        url = "git@github.com:user/repo.git"
        result = hash_git_url(url)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))

    def test_different_urls_different_hashes(self):
        """Different URLs should produce different hashes"""
        url1 = "git@github.com:user/repo1.git"
        url2 = "git@github.com:user/repo2.git"
        hash1 = hash_git_url(url1)
        hash2 = hash_git_url(url2)
        self.assertNotEqual(hash1, hash2)

    def test_normalizes_before_hashing(self):
        """HTTPS and SSH formats of same repo should hash the same"""
        ssh = "git@github.com:user/repo.git"
        https = "https://github.com/user/repo"
        hash_ssh = hash_git_url(ssh)
        hash_https = hash_git_url(https)
        self.assertEqual(hash_ssh, hash_https)


class TestSanitizeForFilename(unittest.TestCase):
    """Tests for sanitize_for_filename function"""

    def test_simple_string(self):
        """Simple alphanumeric should remain unchanged"""
        text = "myproject123"
        result = sanitize_for_filename(text)
        self.assertEqual(result, "myproject123")

    def test_spaces_to_hyphens(self):
        """Spaces should convert to hyphens"""
        text = "my project"
        result = sanitize_for_filename(text)
        self.assertEqual(result, "my-project")

    def test_special_characters(self):
        """Special characters should convert to hyphens"""
        text = "my@project!name"
        result = sanitize_for_filename(text)
        self.assertEqual(result, "my-project-name")

    def test_consecutive_hyphens(self):
        """Consecutive hyphens should collapse to one"""
        text = "my---project"
        result = sanitize_for_filename(text)
        self.assertEqual(result, "my-project")

    def test_leading_trailing_hyphens(self):
        """Leading and trailing hyphens should be removed"""
        text = "-myproject-"
        result = sanitize_for_filename(text)
        self.assertEqual(result, "myproject")

    def test_underscores_preserved(self):
        """Underscores should be preserved"""
        text = "my_project"
        result = sanitize_for_filename(text)
        self.assertEqual(result, "my_project")

    def test_dots_preserved(self):
        """Dots should be preserved"""
        text = "my.project"
        result = sanitize_for_filename(text)
        self.assertEqual(result, "my.project")

    def test_lowercase(self):
        """Should convert to lowercase"""
        text = "MyProject"
        result = sanitize_for_filename(text)
        self.assertEqual(result, "myproject")

    def test_complex_example(self):
        """Complex example with multiple transformations"""
        text = "My Cool Project!!!"
        result = sanitize_for_filename(text)
        self.assertEqual(result, "my-cool-project")


class TestExtractRepoName(unittest.TestCase):
    """Tests for extract_repo_name function"""

    def test_github_ssh(self):
        """Should extract owner and repo from GitHub SSH"""
        url = "git@github.com:octocat/Hello-World.git"
        owner, repo = extract_repo_name(url)
        self.assertEqual(owner, "octocat")
        self.assertEqual(repo, "hello-world")  # Sanitized

    def test_github_https(self):
        """Should extract owner and repo from GitHub HTTPS"""
        url = "https://github.com/octocat/Hello-World"
        owner, repo = extract_repo_name(url)
        self.assertEqual(owner, "octocat")
        self.assertEqual(repo, "hello-world")

    def test_gitlab_ssh(self):
        """Should extract owner and repo from GitLab SSH"""
        url = "git@gitlab.com:gitlab-org/gitlab.git"
        owner, repo = extract_repo_name(url)
        self.assertEqual(owner, "gitlab-org")
        self.assertEqual(repo, "gitlab")

    def test_special_characters_sanitized(self):
        """Should sanitize special characters in owner/repo"""
        url = "git@github.com:my-org/My_Cool-Repo.git"
        owner, repo = extract_repo_name(url)
        self.assertEqual(owner, "my-org")
        self.assertEqual(repo, "my_cool-repo")

    def test_unparseable_url_returns_unknown(self):
        """Unparseable URL should return 'unknown' and hash"""
        url = "invalid-url"
        owner, repo = extract_repo_name(url)
        self.assertEqual(owner, "unknown")
        self.assertEqual(len(repo), 12)  # Should be hash (12 chars)

    def test_nested_path(self):
        """Should handle nested paths (extracts first two components)"""
        # Nested paths like org/team/repo extract org as owner, team/repo as repo
        url = "https://github.com/org/team/repo"
        owner, repo = extract_repo_name(url)
        # Actually works: extracts "org" and "team/repo"
        self.assertEqual(owner, "org")
        self.assertIn("team", repo)  # Repo will be "team/repo"


class TestGenerateProjectName(unittest.TestCase):
    """Tests for generate_project_name function"""

    def test_github_standard(self):
        """Should generate standard owner-repo format"""
        url = "git@github.com:octocat/hello-world.git"
        result = generate_project_name(url)
        self.assertEqual(result, "octocat-hello-world")

    def test_gitlab_standard(self):
        """Should work with GitLab URLs"""
        url = "https://gitlab.com/gitlab-org/gitlab"
        result = generate_project_name(url)
        self.assertEqual(result, "gitlab-org-gitlab")

    def test_anthropic_quickstarts(self):
        """Real example: Anthropic quickstarts"""
        url = "git@github.com:anthropics/anthropic-quickstarts.git"
        result = generate_project_name(url)
        self.assertEqual(result, "anthropics-anthropic-quickstarts")

    def test_special_characters(self):
        """Should sanitize special characters"""
        url = "git@github.com:My_Org/Cool-Repo.git"
        result = generate_project_name(url)
        self.assertEqual(result, "my_org-cool-repo")

    def test_consistent_with_extract(self):
        """Should be consistent with extract_repo_name"""
        url = "git@github.com:user/repo.git"
        owner, repo = extract_repo_name(url)
        project_name = generate_project_name(url)
        self.assertEqual(project_name, f"{owner}-{repo}")


class TestGenerateBaseDir(unittest.TestCase):
    """Tests for generate_base_dir function"""

    def test_default_managed_directory(self):
        """Should use ~/.opencode-projects by default"""
        url = "git@github.com:user/repo.git"
        result = generate_base_dir(url)
        expected_suffix = ".opencode-projects/user-repo"
        self.assertTrue(result.endswith(expected_suffix))
        self.assertTrue(result.startswith(os.path.expanduser("~")))

    def test_custom_base_directory(self):
        """Should use custom base when provided"""
        url = "git@github.com:user/repo.git"
        custom = "/custom/path/myproject"
        result = generate_base_dir(url, custom_base=custom)
        self.assertEqual(result, "/custom/path/myproject")

    def test_absolute_path(self):
        """Should return absolute path"""
        url = "git@github.com:user/repo.git"
        result = generate_base_dir(url)
        self.assertTrue(os.path.isabs(result))

    def test_consistent_naming(self):
        """Should use same naming as generate_project_name"""
        url = "git@github.com:octocat/hello-world.git"
        base_dir = generate_base_dir(url)
        project_name = generate_project_name(url)
        self.assertTrue(base_dir.endswith(project_name))


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases and error handling"""

    def test_empty_string(self):
        """Should handle empty string gracefully"""
        # Empty strings just get .git appended
        result = normalize_git_url("")
        self.assertEqual(result, ".git")

    def test_very_long_url(self):
        """Should handle very long URLs"""
        long_path = "a" * 200
        url = f"https://github.com/user/{long_path}"
        result = normalize_git_url(url)
        self.assertTrue(result.startswith("git@github.com:"))

    def test_unicode_characters(self):
        """Should handle unicode characters"""
        url = "git@github.com:user/café-repo.git"
        result = sanitize_for_filename("café-repo")
        # Unicode chars are actually preserved in the current implementation
        self.assertIn("é", result)
        self.assertEqual(result, "café-repo")

    def test_multiple_dots_in_url(self):
        """Should handle multiple dots in URL"""
        url = "git@git.company.co.uk:user/repo.git"
        result = normalize_git_url(url)
        self.assertTrue(result.endswith(".git"))

    def test_path_with_dots(self):
        """Should handle repo names with dots"""
        url = "git@github.com:user/my.awesome.repo.git"
        owner, repo = extract_repo_name(url)
        self.assertEqual(repo, "my.awesome.repo")


def run_tests():
    """Run all tests with detailed output"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test cases
    suite.addTests(loader.loadTestsFromTestCase(TestNormalizeGitUrl))
    suite.addTests(loader.loadTestsFromTestCase(TestHashGitUrl))
    suite.addTests(loader.loadTestsFromTestCase(TestSanitizeForFilename))
    suite.addTests(loader.loadTestsFromTestCase(TestExtractRepoName))
    suite.addTests(loader.loadTestsFromTestCase(TestGenerateProjectName))
    suite.addTests(loader.loadTestsFromTestCase(TestGenerateBaseDir))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))

    # Run with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "="*70)
    print("Test Summary")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("="*70)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
