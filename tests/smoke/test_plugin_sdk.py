from __future__ import annotations

import subprocess
from pathlib import Path


def test_plugin_sdk_validate_sample_plugin():
    proc = subprocess.run(
        [
            "python3",
            "scripts/plugin_sdk.py",
            "validate",
            "--path",
            "examples/plugins/sample-memory-plugin",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "[ok" in proc.stdout


def test_plugin_sdk_scaffold_and_validate(tmp_path: Path):
    out_dir = tmp_path / "plugins"
    proc_scaffold = subprocess.run(
        [
            "python3",
            "scripts/plugin_sdk.py",
            "scaffold",
            "--name",
            "tmp-memory-plugin",
            "--provider-type",
            "memory",
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_scaffold.returncode == 0, proc_scaffold.stdout + proc_scaffold.stderr

    plugin_path = out_dir / "tmp-memory-plugin"
    proc_validate = subprocess.run(
        [
            "python3",
            "scripts/plugin_sdk.py",
            "validate",
            "--path",
            str(plugin_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_validate.returncode == 0, proc_validate.stdout + proc_validate.stderr
