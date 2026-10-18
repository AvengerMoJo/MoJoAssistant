"""Daily OpenRouter free-model refresh: what is added, disabled, enabled -- and that a bad write is undone."""
import asyncio
import json
from datetime import datetime, timezone

import pytest

from app.scheduler import free_model_refresh as fmr
from app.scheduler.account_expansion import expand_provider_accounts

NOW = datetime(2026, 10, 18, 2, 0, tzinfo=timezone.utc)


def entry(mid, price="0", tools=True, ctx=128000, expires=None):
    e = {"id": mid, "pricing": {"prompt": price, "completion": price}, "context_length": ctx,
         "supported_parameters": ["tools"] if tools else ["temperature"]}
    if expires:
        e["expiration_date"] = expires
    return e


def test_candidates_are_free_tool_capable_unexpired_and_big_enough():
    cat = {"data": [
        entry("a/ok:free"), entry("b/paid:free", price="0.001"), entry("c/notools:free", tools=False),
        entry("d/small:free", ctx=8000), entry("e/gone:free", expires="2026-10-01"), entry("f/future:free", expires="2026-12-01"),
        entry("g/notfree"),
    ]}
    assert sorted(fmr.free_tool_candidates(cat, NOW)) == ["a/ok:free", "f/future:free"]


def configured(*models):
    return [dict(m) if isinstance(m, dict) else {"model": m, "priority": 10} for m in models]


def test_new_working_candidate_is_added_at_low_priority_and_broken_one_is_not():
    cat = {"x:free": entry("x:free"), "y:free": entry("y:free")}
    p = fmr.plan_changes(configured(), cat, {"x:free": True, "y:free": False}, {}, "2026-10-18")
    assert [m["model"] for m in p["add"]] == ["x:free"] and p["add"][0]["priority"] == fmr.NEW_MODEL_PRIORITY


def test_model_missing_from_catalog_is_disabled_at_once():
    p = fmr.plan_changes(configured("gone:free"), {}, {"gone:free": True}, {}, "2026-10-18")
    assert "gone:free" in p["disable"]


def test_three_failed_days_in_a_row_disable_and_one_good_day_resets():
    cat = {"m:free": entry("m:free")}
    hist = {"m:free": {"consecutive_failures": 2}}
    p = fmr.plan_changes(configured("m:free"), cat, {"m:free": False}, hist, "2026-10-18")
    assert "m:free" in p["disable"] and "3 daily checks" in p["disable"]["m:free"]
    p = fmr.plan_changes(configured("m:free"), cat, {"m:free": True}, hist, "2026-10-18")
    assert not p["disable"] and p["history"]["m:free"]["consecutive_failures"] == 0
    p = fmr.plan_changes(configured("m:free"), cat, {"m:free": False}, {"m:free": {"consecutive_failures": 0}}, "2026-10-18")
    assert not p["disable"]


def test_disabled_model_that_is_back_and_answers_is_enabled():
    cat = {"m:free": entry("m:free")}
    p = fmr.plan_changes(configured({"model": "m:free", "enabled": False}), cat, {"m:free": True}, {}, "2026-10-18")
    assert p["enable"] == ["m:free"]


def make_config(tmp_path, models):
    path = tmp_path / "resource_pool.json"
    path.write_text(json.dumps({
        "quota_pools": {"openrouter_free": {"limit": 1000}},
        "provider_accounts": {GROUP: {
            "template": {"type": "api", "provider": "openrouter", "base_url": "u", "tier": "free_api"},
            "quota_pool": "openrouter_free", "accounts": {"a": {"key_var": "K"}}, "models": models}}}))
    return path


GROUP = fmr.GROUP


def test_apply_writes_reads_back_and_keeps_a_backup(tmp_path):
    path = make_config(tmp_path, [{"model": "old:free", "priority": 10}])
    plan = {"add": [{"model": "new:free", "priority": 30}], "disable": {"old:free": "why"}, "enable": []}
    out = fmr.apply_to_config(path, plan, expand_provider_accounts)
    data = json.loads(path.read_text())
    models = {m["model"]: m for m in data["provider_accounts"][GROUP]["models"]}
    assert out["written"] and models["old:free"]["enabled"] is False and models["old:free"]["disabled_reason"] == "why"
    assert "new:free" in models and (tmp_path / "resource_pool.json.bak_freerefresh").exists()


def test_a_config_that_does_not_expand_is_restored(tmp_path):
    path = make_config(tmp_path, [{"model": "old:free", "priority": 10}])
    before = path.read_text()
    plan = {"add": [{"model": "new:free", "priority": 30}], "disable": {}, "enable": []}
    with pytest.raises(fmr.RefreshError):
        fmr.apply_to_config(path, plan, lambda d: ({}, {}, ["broken"]))
    assert path.read_text() == before


def test_empty_catalog_changes_nothing(tmp_path):
    path = make_config(tmp_path, [{"model": "old:free", "priority": 10}])
    before = path.read_text()
    with pytest.raises(fmr.RefreshError, match="catalog came back empty"):
        asyncio.run(fmr.run_refresh(path, tmp_path / "s.json", lambda: {"data": []}, lambda m: True,
                                    expand_provider_accounts, now=NOW))
    assert path.read_text() == before and not (tmp_path / "s.json").exists()


def test_full_run_adds_at_most_three_new_models_and_records_state(tmp_path):
    path = make_config(tmp_path, [{"model": "old:free", "priority": 10}])
    cat = {"data": [entry("old:free")] + [entry(f"n{i}:free") for i in range(5)]}
    state = tmp_path / "s.json"
    summary = asyncio.run(fmr.run_refresh(path, state, lambda: cat, lambda m: True, expand_provider_accounts, now=NOW))
    assert len(summary["added"]) == fmr.MAX_NEW_PER_RUN and summary["config_written"]
    saved = json.loads(state.read_text())
    assert saved["last_run"]["added"] == summary["added"] and saved["models"]["old:free"]["last_ok"] == "2026-10-18"
