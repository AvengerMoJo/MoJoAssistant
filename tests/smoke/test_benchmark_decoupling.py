from pathlib import Path


def test_longmemeval_uses_provider_runtime():
    path = Path("tests/benchmarks/run_longmemeval.py")
    text = path.read_text(encoding="utf-8")
    assert "from tests.benchmarks.provider_runtime import ProviderMemoryRuntime" in text
    assert "from mojo_memory.services.memory_service import MemoryService" not in text
