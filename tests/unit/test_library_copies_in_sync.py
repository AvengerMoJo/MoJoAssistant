"""MoJoAssistant carries byte-identical copies of four resource-manager library modules until it depends on the
library as a package. A copy that drifts changes pool behaviour silently, so any difference fails here.

When the sibling library checkout is absent the test is SKIPPED with the reason -- it cannot prove anything then,
and a skip is visible where a pass would not be."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = Path.home() / "Development" / "Personal" / "ai-resource-manager" / "resource_manager"
COPIES = {
    "quota.py": "app/scheduler/resource_quota.py",
    "expansion.py": "app/scheduler/account_expansion.py",
    "health.py": "app/scheduler/resource_health.py",
    "provider_errors.py": "app/scheduler/provider_errors.py",
}


@pytest.mark.parametrize("library_file,copy", sorted(COPIES.items()))
def test_copy_is_byte_identical_to_the_library(library_file, copy):
    source = LIBRARY / library_file
    if not source.exists():
        pytest.skip(f"library checkout not found at {LIBRARY}; copy drift cannot be checked here")
    assert (ROOT / copy).read_bytes() == source.read_bytes(), (
        f"{copy} differs from ai-resource-manager/resource_manager/{library_file}; "
        "change the library first and copy it over, never edit the copy alone")
