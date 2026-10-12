from app.scheduler.account_expansion import expand_provider_accounts
from app.scheduler.resource_pool import ResourceManager

POOLS = {"free": [{"name": "daily", "kind": "rolling", "seconds": 86400, "max_calls": 1000, "reserved_for_user_pct": 0}]}


def _data(**over):
    d = {
        "resources": {"plain": {"type": "local", "model": "x"}},
        "quota_pools": POOLS,
        "provider_accounts": {"orf": {
            "template": {"type": "api", "provider": "openrouter", "base_url": "https://o/api/v1", "tier": "free_api"},
            "quota_pool": "free",
            "accounts": {"a": {"key_var": "KEY_A"}, "b": {"key_var": "KEY_B"}},
            "models": [{"model": "nvidia/nemotron-3.5-lightning:free", "priority": 11, "context_limit": 1000000}],
        }},
    }
    d.update(over)
    return d


def test_one_resource_per_account_and_model_with_own_quota_pool():
    res, pools, errors = expand_provider_accounts(_data())
    assert errors == []
    ids = sorted(k for k in res if k != "plain")
    assert ids == ["orf_a_nvidia_nemotron_3_5_lightning_free", "orf_b_nvidia_nemotron_3_5_lightning_free"]
    a, b = res[ids[0]], res[ids[1]]
    assert a["key_var"] == "KEY_A" and b["key_var"] == "KEY_B"
    assert a["quota_pool"] == "free__a" and b["quota_pool"] == "free__b"
    assert a["account_group"] == b["account_group"] == "orf_nvidia_nemotron_3_5_lightning_free"
    assert "free__a" in pools and "free__b" in pools and pools["free__a"] is not pools["free__b"]
    assert a["priority"] == 11 and a["tier"] == "free_api"


def test_disabled_account_is_generated_disabled():
    d = _data()
    d["provider_accounts"]["orf"]["accounts"]["b"]["enabled"] = False
    res, _, _ = expand_provider_accounts(d)
    assert res["orf_b_nvidia_nemotron_3_5_lightning_free"]["enabled"] is False
    assert res["orf_a_nvidia_nemotron_3_5_lightning_free"]["enabled"] is True


def test_bad_group_is_reported_not_raised():
    res, _, errors = expand_provider_accounts(_data(provider_accounts={"bad": {"accounts": {}, "models": []},
                                                                       "nopool": {"quota_pool": "missing", "accounts": {"a": {"key_var": "K"}},
                                                                                  "models": [{"model": "m"}]}}))
    assert len(errors) == 2 and list(res) == ["plain"]


def test_account_without_key_var_is_an_error():
    d = _data()
    d["provider_accounts"]["orf"]["accounts"]["c"] = {}
    _, _, errors = expand_provider_accounts(d)
    assert any("orf.c" in e for e in errors)


def test_pool_loads_expanded_accounts_and_disables_the_one_without_a_key(tmp_path, monkeypatch):
    monkeypatch.setenv("KEY_A", "sk-a")
    monkeypatch.delenv("KEY_B", raising=False)
    from unittest.mock import patch
    monkeypatch.setattr(ResourceManager, "USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(ResourceManager, "META_FILE", tmp_path / "meta.json")
    monkeypatch.setattr(ResourceManager, "SANDBOX_ENV_FILE", tmp_path / "none.env")
    monkeypatch.setattr(ResourceManager, "get_loaded_resource_ids", lambda self: set())
    with patch("app.config.config_loader.load_layered_json_config", return_value=_data()):
        rm = ResourceManager(config_path=str(tmp_path / "pool.json"))
    a = rm._resources["orf_a_nvidia_nemotron_3_5_lightning_free"]
    b = rm._resources["orf_b_nvidia_nemotron_3_5_lightning_free"]
    assert a.enabled and a.quota_pool == "free__a"
    assert not b.enabled and "KEY_B" in b.config_error


def test_generated_resources_carry_the_account_health_group():
    res, _, _ = expand_provider_accounts(_data())
    assert res["orf_a_nvidia_nemotron_3_5_lightning_free"]["health_group"] == "orf_a"
    assert res["orf_b_nvidia_nemotron_3_5_lightning_free"]["health_group"] == "orf_b"
