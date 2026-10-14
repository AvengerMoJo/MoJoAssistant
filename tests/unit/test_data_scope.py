"""data_scope: where a request's data may go. A caller's limit filters the pool; a busy resource inside the limit queues, it does not leave it."""
import pytest

from app.scheduler.resource_pool import (
    DATA_SCOPES, LLMResource, ResourceManager, ResourceTier, derive_data_scope,
)


@pytest.mark.parametrize("url,scope", [
    ("http://localhost:1234/v1", "local_host"),
    ("http://127.0.0.1:8000/v1", "local_host"),
    ("http://[::1]:8000/v1", "local_host"),
    ("http://192.168.77.9:2586", "own_network"),
    ("http://10.0.0.5/v1", "own_network"),
    ("http://100.99.1.2:8080/v1", "own_network"),  # another tailnet host
    ("http://evo-x3:1234/v1", "own_network"),
    ("http://evo-x3.lan:1234/v1", "own_network"),
    ("https://openrouter.ai/api/v1", "third_party"),
    ("https://keys.eclipsogate.org/mcp", "third_party"),
    ("http://8.8.8.8/v1", "third_party"),
    ("", "third_party"),
])
def test_scope_is_derived_from_the_address(url, scope):
    assert derive_data_scope(url) == scope


def test_an_address_of_this_host_is_local_host(monkeypatch):
    import app.scheduler.resource_pool as rp
    monkeypatch.setattr(rp, "_is_address_of_this_host", lambda ip: ip == "100.66.212.7")
    assert derive_data_scope("http://100.66.212.7:8080/v1") == "local_host"
    assert derive_data_scope("http://100.66.212.8:8080/v1") == "own_network"


def make(rid, scope, priority, tier=ResourceTier.FREE):
    return LLMResource(id=rid, type="api" if tier != ResourceTier.FREE else "local", provider="openai", base_url="http://x/v1", model=rid,
                       tier=tier, priority=priority, data_scope=scope)


@pytest.fixture
def pool(tmp_path):
    rm = ResourceManager.__new__(ResourceManager)  # no config loading: only the eligibility/selection code runs
    import threading
    rm._lock = threading.RLock()
    rm._resources = {r.id: r for r in [
        make("remote_api", "third_party", 1, ResourceTier.FREE_API),
        make("lan_box", "own_network", 5),
        make("this_host", "local_host", 9),
    ]}
    rm._approved_paid, rm._group_counters = set(), {}
    rm._maybe_reload_runtime_state = lambda: None
    rm._is_rate_limited = lambda r: False
    rm._is_budget_available = lambda r: True
    rm._compute_status = lambda r: __import__("app.scheduler.resource_pool", fromlist=["ResourceStatus"]).ResourceStatus.AVAILABLE
    rm._memory_fit_reason = lambda r: None
    rm.get_loaded_resource_ids = lambda: {"lan_box", "this_host"}
    rm.get_busy_resource_ids = lambda: set()
    return rm


def test_no_limit_picks_by_priority(pool):
    assert pool.acquire().id == "remote_api"


def test_own_network_limit_skips_third_party(pool):
    assert pool.acquire(max_data_scope="own_network").id == "lan_box"


def test_local_host_limit_allows_only_this_host(pool):
    assert pool.acquire(max_data_scope="local_host").id == "this_host"


def test_busy_resource_inside_the_scope_still_beats_leaving_it(pool):
    pool.get_busy_resource_ids = lambda: {"lan_box", "this_host"}
    assert pool.acquire(max_data_scope="own_network").id == "lan_box"  # queues, does not go to remote_api


def test_nothing_inside_the_scope_returns_none_and_says_why(pool):
    del pool._resources["lan_box"], pool._resources["this_host"]
    assert pool.acquire(max_data_scope="own_network") is None
    rows = pool.selection_order(max_data_scope="own_network")
    assert rows[0]["excluded_because"] == "data scope third_party is wider than the allowed own_network"


def test_unknown_scope_is_an_error(pool):
    with pytest.raises(ValueError):
        pool.acquire(max_data_scope="somewhere")


def test_scopes_are_ordered_narrow_to_wide():
    assert DATA_SCOPES == ("local_host", "own_network", "third_party")
