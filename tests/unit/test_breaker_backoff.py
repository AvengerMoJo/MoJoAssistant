"""A resource that keeps failing after the breaker reopens is retried less and less often, one failure at a time."""
import time

from app.scheduler.resource_pool import ResourceManager, ResourceStatus, UsageRecord


def manager():
    rm = ResourceManager.__new__(ResourceManager)
    return rm


def test_wait_doubles_with_each_failed_recovery_and_is_capped():
    rm = manager()
    waits = [rm._recovery_wait_s(UsageRecord(failed_recoveries=n)) for n in (0, 1, 2, 20)]
    assert waits == [300, 600, 1200, 6 * 3600]


def test_trial_call_after_recovery_trips_on_one_failure_and_waits_longer():
    rm = manager()
    rm._usage, rm._health = {}, {}
    rm._persist_usage = lambda: None
    r = type("R", (), {"id": "x", "enabled": True})()
    u = rm._usage["x"] = UsageRecord(consecutive_errors=5, last_call_at=time.time() - 301)
    # first window (300 s) elapsed: half-open, one more failure trips again
    try:
        rm._compute_status(r)
    except AttributeError:
        pass  # later checks need a full manager; only the breaker state matters here
    assert u.failed_recoveries == 1 and u.consecutive_errors == 4
    u.consecutive_errors += 1
    u.last_call_at = time.time() - 301
    assert rm._compute_status(r) == ResourceStatus.UNREACHABLE  # 600 s window now, 301 s is not enough


def test_provider_overload_counts_against_every_account_of_that_model():
    rm = manager()
    rm._lock = __import__("threading").RLock()
    rm._persist_usage = lambda: None
    rm._quota_pools, rm._pool_calls = {}, {}
    mk = lambda i, m: type("R", (), {"id": i, "model": m, "base_url": "u", "quota_pool": None, "quotas": None, "credential_engine": False})()
    rm._resources = {"a": mk("a", "nemo"), "b": mk("b", "nemo"), "c": mk("c", "other")}
    rm._usage = {}
    rm.record_usage("a", success=False, error_message="Upstream error from Nvidia: Service temporarily overloaded (code 503)")
    assert rm._usage["a"].consecutive_errors == 1 and rm._usage["b"].consecutive_errors == 1
    assert "c" not in rm._usage
    rm.record_usage("a", success=False, error_message="HTTP 401 bad key")
    assert rm._usage["a"].consecutive_errors == 2 and rm._usage["b"].consecutive_errors == 1
