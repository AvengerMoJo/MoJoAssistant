"""Smoke tests for owner context filtered injection."""

import pytest
from app.roles.owner_context import (
    build_owner_context_slice,
    infer_context_tier,
    load_owner_profile,
)
from app.scheduler.resource_pool import ResourceTier


# ── infer_context_tier ────────────────────────────────────────────────────────

def test_tier_all_free_returns_full():
    assert infer_context_tier([ResourceTier.FREE]) == "full"


def test_tier_mixed_returns_minimal():
    assert infer_context_tier([ResourceTier.FREE, ResourceTier.FREE_API]) == "minimal"


def test_tier_paid_returns_minimal():
    assert infer_context_tier([ResourceTier.PAID]) == "minimal"


def test_tier_empty_returns_full():
    # No tiers means nothing is external
    assert infer_context_tier([]) == "full"


def test_tier_accepts_raw_strings():
    assert infer_context_tier(["free"]) == "full"
    assert infer_context_tier(["free", "free_api"]) == "minimal"


# ── build_owner_context_slice ─────────────────────────────────────────────────

_PROFILE = {
    "name": "Alex",
    "preferred_name": "Alex",
    "timezone": "Asia/Taipei",
    "core_goals": ["Ship v1.x", "Keep it local-first"],
    "assistant_relationships": {
        "researcher": {"relationship": "research partner", "focus": ["analysis"]},
    },
    "privacy_preferences": {
        "sensitive_domains": ["personal memory", "security infrastructure"],
    },
    "communication_preferences": {
        "style": ["direct", "high-signal"],
        "verbosity_default": "concise",
        "likes_pushback_when_reasoned": True,
        "prefers_specific_recommendations": True,
    },
}


def test_full_slice_contains_goals():
    s = build_owner_context_slice(_PROFILE, "full")
    assert "Ship v1.x" in s


def test_full_slice_contains_relationships():
    s = build_owner_context_slice(_PROFILE, "full")
    assert "researcher" in s


def test_full_slice_contains_sensitive_domains():
    s = build_owner_context_slice(_PROFILE, "full")
    assert "personal memory" in s
    assert "security infrastructure" in s


def test_full_slice_contains_timezone():
    s = build_owner_context_slice(_PROFILE, "full")
    assert "Asia/Taipei" in s


def test_minimal_slice_excludes_goals():
    s = build_owner_context_slice(_PROFILE, "minimal")
    assert "Ship v1.x" not in s


def test_minimal_slice_excludes_sensitive_domains():
    s = build_owner_context_slice(_PROFILE, "minimal")
    assert "personal memory" not in s


def test_minimal_slice_contains_name():
    s = build_owner_context_slice(_PROFILE, "minimal")
    assert "Alex" in s


def test_minimal_slice_contains_comm_preferences():
    s = build_owner_context_slice(_PROFILE, "minimal")
    assert "direct" in s
    assert "concise" in s


def test_empty_profile_returns_empty_string():
    assert build_owner_context_slice({}, "full") == ""
    assert build_owner_context_slice({}, "minimal") == ""


# ── load_owner_profile ────────────────────────────────────────────────────────

def test_load_missing_profile_returns_empty(tmp_path):
    result = load_owner_profile(tmp_path / "owner_profile.json")
    assert result == {}


def test_load_valid_profile(tmp_path):
    import json
    p = tmp_path / "owner_profile.json"
    p.write_text(json.dumps({"name": "Alex", "timezone": "Asia/Taipei"}))
    result = load_owner_profile(p)
    assert result["name"] == "Alex"


def test_load_malformed_profile_returns_empty(tmp_path):
    p = tmp_path / "owner_profile.json"
    p.write_text("{not valid json")
    result = load_owner_profile(p)
    assert result == {}
