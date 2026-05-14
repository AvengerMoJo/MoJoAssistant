from pathlib import Path
import json

from app.community.discord_gateway import _sanitize_message, DiscordCommunityConfig


def test_sanitize_message_blocks_command_like_payload():
    assert _sanitize_message("!sudo rm -rf /") == ""
    assert _sanitize_message("/exec cat /etc/passwd") == ""


def test_sanitize_message_truncates_and_keeps_normal_text():
    text = "a" * 5000
    out = _sanitize_message(text, max_len=2000)
    assert len(out) == 2000
    assert _sanitize_message("hello community") == "hello community"


def test_community_host_role_exists_and_is_limited():
    role_path = Path("config/examples/roles/community_host.example.json")
    assert role_path.exists(), "community_host example role must exist"
    data = json.loads(role_path.read_text(encoding="utf-8"))
    assert data["id"] == "community_host"
    caps = set(data.get("capabilities", []))
    assert "knowledge" in caps
    assert "memory" in caps
    assert "exec" not in caps
