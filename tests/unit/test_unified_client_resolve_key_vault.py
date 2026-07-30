"""
Tests for UnifiedLLMClient.resolve_key()'s key_ref → shared vault step
(Phase A of the unified provider/resource-pool work). Additive: existing
key_var/api_key_env/inline api_key configs must be completely unaffected.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from app.llm.unified_client import UnifiedLLMClient


class TestResolveKeyVault:
    def test_key_ref_resolves_from_vault(self, tmp_path):
        vault_path = tmp_path / "api_keys.json"
        vault_path.write_text(json.dumps({"zai_key": "sk-from-vault"}), encoding="utf-8")
        with patch("app.scheduler.key_vault.VAULT_PATH", vault_path):
            result = UnifiedLLMClient.resolve_key("some_resource", {"key_ref": "zai_key"})
        assert result == "sk-from-vault"

    def test_key_ref_missing_from_vault_falls_through_to_inline(self, tmp_path):
        vault_path = tmp_path / "api_keys.json"
        vault_path.write_text(json.dumps({}), encoding="utf-8")
        with patch("app.scheduler.key_vault.VAULT_PATH", vault_path):
            result = UnifiedLLMClient.resolve_key(
                "some_resource", {"key_ref": "not_in_vault", "api_key": "sk-inline"}
            )
        assert result == "sk-inline"

    def test_no_key_ref_is_completely_unaffected(self):
        result = UnifiedLLMClient.resolve_key("some_resource", {"api_key": "sk-inline"})
        assert result == "sk-inline"

    def test_key_var_still_takes_precedence_over_stale_no_op(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_KEY_VAR", "sk-from-env")
        result = UnifiedLLMClient.resolve_key(
            "some_resource", {"key_var": "MY_TEST_KEY_VAR", "api_key": "sk-inline"}
        )
        assert result == "sk-from-env"
