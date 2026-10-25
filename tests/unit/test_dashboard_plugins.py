import pytest

from app.dashboard import plugins
from app.dashboard import router as dash


def test_valid_panel_and_each_kind_of_bad_one():
    ok = plugins.validate_panel({"id": "resource_manager", "title": "Resource Manager", "url": "http://127.0.0.1:8700/ui"})
    assert ok["mode"] == "iframe"
    for bad in ({"id": "A B", "title": "t", "url": "http://x"}, {"id": "a", "title": "", "url": "http://x"},
                {"id": "a", "title": "t", "url": "javascript:alert(1)"}, {"id": "a", "title": "t", "url": "/relative"},
                {"id": "a", "title": "t", "url": "http://x", "mode": "popup"}, {"id": "a", "title": "t", "url": "http://x", "extra": 1}, "x"):
        with pytest.raises(ValueError):
            plugins.validate_panel(bad)


def test_bad_entries_are_skipped_not_fatal_and_duplicates_dropped(monkeypatch):
    monkeypatch.setattr(plugins, "load_layered_json_config", lambda p: {"panels": [
        {"id": "a", "title": "A", "url": "http://h/1"}, {"id": "a", "title": "dup", "url": "http://h/2"},
        {"id": "b b", "title": "bad", "url": "http://h/3"}, {"id": "c", "title": "C", "url": "http://h/4", "mode": "link"}]})
    assert [p["id"] for p in plugins.load_panels()] == ["a", "c"]


def test_unreadable_config_gives_no_panels(monkeypatch):
    def boom(p):
        raise ValueError("bad json")
    monkeypatch.setattr(plugins, "load_layered_json_config", boom)
    assert plugins.load_panels() == []


def test_nav_gets_one_escaped_entry_per_panel(monkeypatch):
    monkeypatch.setattr(plugins, "load_layered_json_config", lambda p: {"panels": [
        {"id": "rm", "title": "Resource <b>Manager</b>", "url": "http://127.0.0.1:8700/ui"},
        {"id": "ext", "title": "Ext", "url": "https://example.com/x", "mode": "link"}]})
    nav = dash._nav()
    assert 'href="/dashboard/plugins/rm"' in nav and "Resource &lt;b&gt;Manager" in nav and "<b>" not in nav.split("Resource")[1][:20]
    assert 'href="https://example.com/x" target="_blank"' in nav and "{plugin_links}" not in nav


def test_panel_page_frames_the_configured_url_and_unknown_panel_is_404(monkeypatch):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.dashboard.auth import make_token
    monkeypatch.setattr(plugins, "load_layered_json_config", lambda p: {"panels": [
        {"id": "rm", "title": "Resource Manager", "url": "http://127.0.0.1:8700/ui"}]})
    app = FastAPI(); app.include_router(dash.router)
    c = TestClient(app, follow_redirects=False)
    assert c.get("/dashboard/plugins/rm").status_code == 303                       # needs the dashboard login
    c.cookies.set("mojo_dash", make_token())
    r = c.get("/dashboard/plugins/rm")
    assert r.status_code == 200 and '<iframe src="http://127.0.0.1:8700/ui"' in r.text and "sandbox=" in r.text
    assert c.get("/dashboard/plugins/nope").status_code == 404
