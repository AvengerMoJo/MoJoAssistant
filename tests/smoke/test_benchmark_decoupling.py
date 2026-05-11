from pathlib import Path


def test_longmemeval_uses_provider_runtime():
    path = Path("tests/benchmarks/run_longmemeval.py")
    text = path.read_text(encoding="utf-8")
    assert "from tests.benchmarks.provider_runtime import ProviderMemoryRuntime" in text
    assert "from mojo_memory.services.memory_service import MemoryService" not in text


def test_run_locomo_no_toplevel_app_import():
    """run_locomo.py must not import app.* at module level."""
    path = Path("tests/benchmarks/run_locomo.py")
    lines = path.read_text(encoding="utf-8").splitlines()
    top_level_app_imports = [
        l for l in lines
        if l.startswith("from app.") or l.startswith("import app.")
    ]
    assert not top_level_app_imports, (
        f"run_locomo.py has top-level app imports: {top_level_app_imports}"
    )


def test_run_locomo_abcd_e2e_no_toplevel_app_import():
    """run_locomo_abcd_e2e.py must not import app.* at module level."""
    path = Path("tests/benchmarks/run_locomo_abcd_e2e.py")
    lines = path.read_text(encoding="utf-8").splitlines()
    top_level_app_imports = [
        l for l in lines
        if l.startswith("from app.") or l.startswith("import app.")
    ]
    assert not top_level_app_imports, (
        f"run_locomo_abcd_e2e.py has top-level app imports: {top_level_app_imports}"
    )
