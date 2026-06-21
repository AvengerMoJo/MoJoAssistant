"""Unit tests for git_identity module — ensures sandbox commits are attributed
to the real user, not 'opencode@local'."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestLoadGitIdentity(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.config_path = self.tmp / "git_identity.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_default_only(self):
        self.config_path.write_text(json.dumps({
            "default": {
                "name": "Alex",
                "email": "alex@personal.com",
                "assistant_attribution": "Assistant Popo@MoJoAssistant Implementation",
            }
        }))
        with patch("app.sandbox.git_identity._config_path", return_value=self.config_path):
            from app.sandbox.git_identity import load_git_identity
            ident = load_git_identity()
            self.assertEqual(ident.name, "Alex")
            self.assertEqual(ident.email, "alex@personal.com")
            self.assertEqual(ident.assistant_attribution,
                             "Assistant Popo@MoJoAssistant Implementation")

    def test_per_repo_override(self):
        self.config_path.write_text(json.dumps({
            "default": {
                "name": "Alex",
                "email": "alex@personal.com",
                "assistant_attribution": "Personal",
            },
            "overrides": {
                "CompanyOrg/secret-repo": {
                    "email": "alex@company.com",
                    "assistant_attribution": "Work assistant",
                }
            }
        }))
        with patch("app.sandbox.git_identity._config_path", return_value=self.config_path):
            from app.sandbox.git_identity import load_git_identity
            # Personal repo uses default
            ident = load_git_identity("git@github.com:Alex/fun-project.git")
            self.assertEqual(ident.email, "alex@personal.com")
            # Work repo uses override
            ident = load_git_identity("git@github.com:CompanyOrg/secret-repo.git")
            self.assertEqual(ident.email, "alex@company.com")
            self.assertEqual(ident.assistant_attribution, "Work assistant")

    def test_per_repo_override_keeps_default_name(self):
        """Override can omit 'name' — falls back to default name."""
        self.config_path.write_text(json.dumps({
            "default": {"name": "Alex", "email": "default@example.com"},
            "overrides": {
                "foo/bar": {"email": "work@example.com"},
            }
        }))
        with patch("app.sandbox.git_identity._config_path", return_value=self.config_path):
            from app.sandbox.git_identity import load_git_identity
            ident = load_git_identity("git@github.com:foo/bar.git")
            self.assertEqual(ident.name, "Alex")  # from default
            self.assertEqual(ident.email, "work@example.com")  # from override

    def test_extract_repo_key_variants(self):
        from app.sandbox.git_identity import _extract_repo_key
        self.assertEqual(_extract_repo_key("git@github.com:AvengerMoJo/mcp-service.git"),
                         "AvengerMoJo/mcp-service")
        self.assertEqual(_extract_repo_key("https://github.com/AvengerMoJo/mcp-service.git"),
                         "AvengerMoJo/mcp-service")
        self.assertEqual(_extract_repo_key("https://gitlab.com/foo/bar"),
                         "foo/bar")
        self.assertEqual(_extract_repo_key("git@custom:Org/Repo.git"),
                         "Org/Repo")

    def test_fallback_when_no_config_file(self):
        with patch("app.sandbox.git_identity._config_path",
                   return_value=self.tmp / "nonexistent.json"):
            from app.sandbox.git_identity import load_git_identity
            ident = load_git_identity()
            self.assertEqual(ident.email, "avengermojo@gmail.com")

    def test_fallback_when_config_broken(self):
        self.config_path.write_text("{ invalid json")
        with patch("app.sandbox.git_identity._config_path", return_value=self.config_path):
            from app.sandbox.git_identity import load_git_identity
            ident = load_git_identity()  # should not raise
            self.assertEqual(ident.email, "avengermojo@gmail.com")


class TestGitIdentityToEnv(unittest.TestCase):

    def test_env_vars_for_git(self):
        from app.sandbox.git_identity import GitIdentity
        ident = GitIdentity(
            name="Alex",
            email="alex@example.com",
            assistant_attribution="Bot did this",
        )
        env = ident.to_env()
        self.assertEqual(env["GIT_AUTHOR_NAME"], "Alex")
        self.assertEqual(env["GIT_AUTHOR_EMAIL"], "alex@example.com")
        self.assertEqual(env["GIT_COMMITTER_NAME"], "Alex")
        self.assertEqual(env["GIT_COMMITTER_EMAIL"], "alex@example.com")

    def test_commit_trailer(self):
        from app.sandbox.git_identity import GitIdentity
        ident_with = GitIdentity(name="Alex", email="a@x.com", assistant_attribution="Bot did this")
        self.assertEqual(ident_with.commit_trailer, "\n\nBot did this")
        ident_without = GitIdentity(name="Alex", email="a@x.com")
        self.assertEqual(ident_without.commit_trailer, "")


class TestConfigureRepoGitIdentity(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo_dir = self.tmp / "repo"
        self.repo_dir.mkdir()
        subprocess.run(["git", "init", str(self.repo_dir)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"],
                       cwd=str(self.repo_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=str(self.repo_dir), check=True, capture_output=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_configure_sets_name_and_email(self):
        from app.sandbox.git_identity import GitIdentity, configure_repo_git_identity
        identity = GitIdentity(name="Alex", email="avengermojo@gmail.com")
        configure_repo_git_identity(self.repo_dir, identity)

        name = subprocess.run(
            ["git", "config", "user.name"], cwd=str(self.repo_dir),
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        email = subprocess.run(
            ["git", "config", "user.email"], cwd=str(self.repo_dir),
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        self.assertEqual(name, "Alex")
        self.assertEqual(email, "avengermojo@gmail.com")

    def test_configure_skips_non_git_dir(self):
        """Non-git dir should be a no-op, not crash."""
        from app.sandbox.git_identity import GitIdentity, configure_repo_git_identity
        not_a_repo = self.tmp / "not_a_repo"
        not_a_repo.mkdir()
        identity = GitIdentity(name="Alex", email="a@x.com")
        configure_repo_git_identity(not_a_repo, identity)  # should not raise


if __name__ == "__main__":
    unittest.main()
