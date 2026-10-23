"""Slots, queue waits and breaker state live in the ResourceManager object, so every part of the service
(scheduler, owner chats, dreaming, MCP tools, dashboard, Discord) must use the same one."""
import re
import threading
from pathlib import Path

from app.scheduler import resource_pool as rp

# Probes and CLI diagnostics that deliberately read a fresh pool; everything else in app/ must share.
FRESH_POOL_ALLOWED = {
    "app/scheduler/resource_pool.py",
    "app/config/doctor.py",
    "app/scheduler/agentic_smoke_test.py",
    "app/scheduler/evals/runner.py",
}


def test_same_object_every_time_and_across_threads(monkeypatch):
    made = []

    class Fake:
        def __init__(self, logger=None):
            made.append(self)

    monkeypatch.setattr(rp, "ResourceManager", Fake)
    rp.reset_shared_resource_manager()
    got = []
    threads = [threading.Thread(target=lambda: got.append(rp.get_shared_resource_manager())) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(made) == 1 and all(g is made[0] for g in got)
    rp.reset_shared_resource_manager()
    assert rp.get_shared_resource_manager() is not made[0]
    rp.reset_shared_resource_manager()


def test_service_code_never_builds_its_own_pool():
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in (root / "app").rglob("*.py"):
        rel = str(path.relative_to(root))
        if rel in FRESH_POOL_ALLOWED:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"(?<![\w.])ResourceManager\(", code) and not code.lstrip().startswith(("class ", '"""', "'''")):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert not offenders, "use get_shared_resource_manager():\n" + "\n".join(offenders)
