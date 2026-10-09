"""The registry entry records which coding-agent backend speaks a project's OpenCode server."""
import json

from app.mcp.opencode.config_manager import ConfigManager


def _servers(tmp_path):
    return {s["id"]: s for s in json.loads((tmp_path / "opencode-mcp-tool-servers.json").read_text())["servers"]}


def test_backend_type_recorded_on_add_and_updated_on_restart(tmp_path):
    cm = ConfigManager(str(tmp_path))
    url = "git@github.com:owner/repo.git"
    cm.add_server(git_url=url, port=4200, password="pw", backend_type="opencode_v2")
    entry = next(iter(_servers(tmp_path).values()))
    assert entry["backend_type"] == "opencode_v2"
    cm.add_server(git_url=url, port=4201, password="pw", backend_type="opencode")
    assert next(iter(_servers(tmp_path).values()))["backend_type"] == "opencode"


def test_backend_type_omitted_when_not_given(tmp_path):
    cm = ConfigManager(str(tmp_path))
    cm.add_server(git_url="git@github.com:owner/repo.git", port=4200, password="pw")
    assert "backend_type" not in next(iter(_servers(tmp_path).values()))
