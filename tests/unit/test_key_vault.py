"""
Tests for app.scheduler.key_vault — the minimal shared API key vault
(Phase A of the unified provider/resource-pool work). One flat
{name: secret} JSON file instead of keys scattered across
resource_pool.json's inline api_key/api_key_env and OpenCode's per-server
password field.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.scheduler.coding_agent_executor import CodingAgentExecutor
from app.scheduler.key_vault import resolve_api_key


class TestResolveApiKey:
    def test_returns_none_when_name_is_falsy(self):
        assert resolve_api_key(None) is None
        assert resolve_api_key("") is None

    def test_returns_none_when_vault_file_missing(self, tmp_path):
        with patch("app.scheduler.key_vault.VAULT_PATH", tmp_path / "does_not_exist.json"):
            assert resolve_api_key("some_key") is None

    def test_returns_secret_when_present(self, tmp_path):
        vault_path = tmp_path / "api_keys.json"
        vault_path.write_text(json.dumps({"zai_key": "sk-real-secret"}), encoding="utf-8")
        with patch("app.scheduler.key_vault.VAULT_PATH", vault_path):
            assert resolve_api_key("zai_key") == "sk-real-secret"

    def test_returns_none_when_name_not_found(self, tmp_path):
        vault_path = tmp_path / "api_keys.json"
        vault_path.write_text(json.dumps({"other_key": "sk-x"}), encoding="utf-8")
        with patch("app.scheduler.key_vault.VAULT_PATH", vault_path):
            assert resolve_api_key("zai_key") is None

    def test_returns_none_on_malformed_json(self, tmp_path):
        vault_path = tmp_path / "api_keys.json"
        vault_path.write_text("{not valid json", encoding="utf-8")
        with patch("app.scheduler.key_vault.VAULT_PATH", vault_path):
            assert resolve_api_key("zai_key") is None


class TestPasswordRefWiring:
    """
    CodingAgentExecutor._get_registry() resolves each ServerEntry's
    password_ref (an extra field, since ServerEntry allows extras) into a
    real password via the vault, before BackendRegistry.reload() consumes
    the entries. Existing inline `password` fields are unaffected.
    """

    def _make_executor(self) -> CodingAgentExecutor:
        return CodingAgentExecutor(resource_manager=SimpleNamespace())

    def test_password_ref_resolved_from_vault(self, tmp_path):
        vault_path = tmp_path / "api_keys.json"
        vault_path.write_text(json.dumps({"opencode_basic_auth": "vault-password"}), encoding="utf-8")

        entry = SimpleNamespace(id="x", password="original", password_ref="opencode_basic_auth")
        cfg = SimpleNamespace(servers=[entry], default_server=None)

        executor = self._make_executor()
        mock_registry = MagicMock()
        with patch("app.scheduler.key_vault.VAULT_PATH", vault_path), \
             patch("coding_agent_mcp.backends.BackendRegistry", return_value=mock_registry), \
             patch("coding_agent_mcp.config.loader.load_config", return_value=cfg):
            executor._get_registry()

        assert entry.password == "vault-password"

    def test_no_password_ref_leaves_inline_password_untouched(self, tmp_path):
        vault_path = tmp_path / "api_keys.json"
        vault_path.write_text(json.dumps({}), encoding="utf-8")

        entry = SimpleNamespace(id="x", password="original")
        cfg = SimpleNamespace(servers=[entry], default_server=None)

        executor = self._make_executor()
        mock_registry = MagicMock()
        with patch("app.scheduler.key_vault.VAULT_PATH", vault_path), \
             patch("coding_agent_mcp.backends.BackendRegistry", return_value=mock_registry), \
             patch("coding_agent_mcp.config.loader.load_config", return_value=cfg):
            executor._get_registry()

        assert entry.password == "original"

    def test_password_ref_missing_from_vault_leaves_original_password(self, tmp_path):
        vault_path = tmp_path / "api_keys.json"
        vault_path.write_text(json.dumps({}), encoding="utf-8")

        entry = SimpleNamespace(id="x", password="original", password_ref="not_in_vault")
        cfg = SimpleNamespace(servers=[entry], default_server=None)

        executor = self._make_executor()
        mock_registry = MagicMock()
        with patch("app.scheduler.key_vault.VAULT_PATH", vault_path), \
             patch("coding_agent_mcp.backends.BackendRegistry", return_value=mock_registry), \
             patch("coding_agent_mcp.config.loader.load_config", return_value=cfg):
            executor._get_registry()

        assert entry.password == "original"
