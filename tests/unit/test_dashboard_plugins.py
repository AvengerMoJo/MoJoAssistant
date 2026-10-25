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


def test_remote_panel_validation():
    ok = plugins.validate_panel({"id": "rm", "title": "RM", "url": "https://h/ui/embed/", "mode": "remote", "key_var": "RM_TOKEN"})
    assert ok["key_var"] == "RM_TOKEN"
    for bad in ({"id": "rm", "title": "RM", "url": "http://h", "mode": "remote"},                       # no key_var
                {"id": "rm", "title": "RM", "url": "http://h", "mode": "remote", "key_var": "sk-literal-secret"},
                {"id": "rm", "title": "RM", "url": "http://h", "mode": "iframe", "key_var": "X"}):
        with pytest.raises(ValueError):
            plugins.validate_panel(bad)


def test_remote_panel_is_fetched_by_the_server_with_the_token(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.dashboard.auth import make_token
    seen = []

    def upstream(request):
        seen.append((str(request.url), request.headers.get("authorization")))
        if request.url.path.endswith("/boom"):
            raise httpx.ConnectError("down")
        return httpx.Response(200, text="<html>panel</html>", headers={"content-type": "text/html; charset=utf-8"})
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(upstream), **kw))
    monkeypatch.setattr(plugins, "load_layered_json_config", lambda p: {"panels": [
        {"id": "rm", "title": "RM", "url": "http://remote.example:8700/ui/embed/", "mode": "remote", "key_var": "RM_TEST_TOKEN"}]})
    app = FastAPI(); app.include_router(dash.router)
    c = TestClient(app, follow_redirects=False)
    assert c.get("/dashboard/plugins/rm/view/").status_code == 303                  # dashboard login still required
    c.cookies.set("mojo_dash", make_token())
    monkeypatch.delenv("RM_TEST_TOKEN", raising=False)
    r = c.get("/dashboard/plugins/rm/view/")
    assert r.status_code == 502 and "RM_TEST_TOKEN" in r.text and not seen          # missing token = explicit error
    monkeypatch.setenv("RM_TEST_TOKEN", "tok-123")
    r = c.get("/dashboard/plugins/rm/view/api/snapshot?days=3")
    assert r.status_code == 200 and "panel" in r.text and r.headers["x-frame-options"] == "SAMEORIGIN"
    assert seen[-1] == ("http://remote.example:8700/ui/embed/api/snapshot?days=3", "Bearer tok-123")
    assert "tok-123" not in r.text and "tok-123" not in str(r.headers)
    assert c.get("/dashboard/plugins/rm/view/../x").status_code in (400, 404) or "../" not in seen[-1][0]
    assert c.get("/dashboard/plugins/rm/view/boom").status_code == 502              # unreachable = explicit error
    assert 'src="/dashboard/plugins/rm/view/"' in c.get("/dashboard/plugins/rm").text   # the browser only sees this origin
    assert c.get("/dashboard/plugins/nope/view/").status_code == 404
