"""
MoJoAssistant Dashboard — read-only monitoring UI.

Routes:
  GET  /dashboard/login     — login form
  POST /dashboard/login     — authenticate
  GET  /dashboard/logout    — clear session
  GET  /dashboard           — overview (queue stats + recent events)
  GET  /dashboard/tasks     — task list
  GET  /dashboard/tasks/{id}— task detail + session transcript
  GET  /dashboard/events    — full event log
  GET  /dashboard/roles     — roles overview
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dashboard.auth import COOKIE_NAME, check_password, make_token, verify_token
from app.config.paths import get_memory_path

router = APIRouter(prefix="/dashboard")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mem(*parts: str) -> Path:
    return Path(get_memory_path()).joinpath(*parts)


def _load_json(path: Path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _ts(iso: str | None) -> str:
    """Format ISO timestamp to short human-readable string."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return iso[:16]


def _ago(iso: str | None) -> str:
    """Return 'X min ago' style string."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        delta = datetime.now(dt.tzinfo) - dt
        s = int(delta.total_seconds())
        if s < 60:
            return f"{s}s ago"
        if s < 3600:
            return f"{s // 60}m ago"
        if s < 86400:
            return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"
    except Exception:
        return "—"


# ---------------------------------------------------------------------------
# HTML shell
# ---------------------------------------------------------------------------

_NAV = """
<nav>
  <a href="/dashboard">Overview</a>
  <a href="/dashboard/tasks">Tasks</a>
  <a href="/dashboard/events">Events</a>
  <a href="/dashboard/roles">Roles</a>
  <a href="/dashboard/logout" style="float:right;color:#888">logout</a>
</nav>
"""

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'SF Mono', 'Fira Code', monospace; background: #0f0f0f; color: #d4d4d4; font-size: 13px; }
nav { background: #1a1a1a; padding: 10px 20px; border-bottom: 1px solid #333; }
nav a { color: #7ec8e3; text-decoration: none; margin-right: 20px; }
nav a:hover { color: #fff; }
.page { padding: 20px; max-width: 1200px; margin: 0 auto; }
h1 { font-size: 18px; color: #fff; margin-bottom: 16px; }
h2 { font-size: 14px; color: #aaa; margin: 20px 0 10px; text-transform: uppercase; letter-spacing: 1px; }
.cards { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
.card { background: #1a1a1a; border: 1px solid #333; border-radius: 6px; padding: 14px 20px; min-width: 130px; }
.card .num { font-size: 28px; font-weight: bold; color: #7ec8e3; }
.card .lbl { color: #888; font-size: 11px; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; padding: 8px 10px; border-bottom: 1px solid #333; }
td { padding: 7px 10px; border-bottom: 1px solid #1e1e1e; vertical-align: top; }
tr:hover td { background: #1a1a1a; }
a { color: #7ec8e3; text-decoration: none; }
a:hover { text-decoration: underline; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; }
.s-pending    { background: #2a2a00; color: #ffd700; }
.s-running    { background: #002a00; color: #7ec87e; }
.s-completed  { background: #001a2a; color: #7ec8e3; }
.s-failed     { background: #2a0000; color: #e37e7e; }
.s-waiting_for_input { background: #2a1a00; color: #e3c07e; }
.s-dreaming   { background: #1a002a; color: #c07ee3; }
.lvl0 { color: #555; }
.lvl1 { color: #888; }
.lvl2 { color: #aaa; }
.lvl3 { color: #ffd700; }
.lvl4 { color: #ff8c00; }
.lvl5 { color: #ff4444; font-weight: bold; }
.pre { background: #111; border: 1px solid #2a2a2a; border-radius: 4px; padding: 12px; white-space: pre-wrap; word-break: break-word; line-height: 1.5; max-height: 600px; overflow-y: auto; font-size: 12px; }
.filters { margin-bottom: 14px; }
.filters a { margin-right: 10px; color: #888; }
.filters a.active { color: #7ec8e3; border-bottom: 1px solid #7ec8e3; }
.iter { background: #161616; border-left: 3px solid #333; margin: 6px 0; padding: 8px 12px; border-radius: 0 4px 4px 0; }
.iter.tool_use { border-color: #7ec8e3; }
.iter.final    { border-color: #7ec87e; }
.iter.error    { border-color: #e37e7e; }
"""

def _page(title: str, body: str, nav: bool = True) -> HTMLResponse:
    nav_html = _NAV if nav else ""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — MoJo</title>
  <style>{_CSS}</style>
</head>
<body>
{nav_html}
<div class="page">
{body}
</div>
</body>
</html>""")


def _badge(status: str) -> str:
    return f'<span class="badge s-{status}">{status}</span>'


def _require_auth(session: str | None):
    """Return redirect to login if not authenticated, else None."""
    if not verify_token(session):
        return RedirectResponse("/dashboard/login", status_code=303)
    return None


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(error: str = ""):
    err = '<p style="color:#e37e7e;margin-bottom:12px">Wrong password.</p>' if error else ""
    return _page("Login", f"""
<div style="max-width:340px;margin:80px auto">
  <h1 style="margin-bottom:20px">MoJo Dashboard</h1>
  {err}
  <form method="post" action="/dashboard/login">
    <input name="password" type="password" placeholder="Password"
           style="width:100%;padding:10px;background:#1a1a1a;border:1px solid #444;color:#d4d4d4;border-radius:4px;margin-bottom:10px">
    <button type="submit"
            style="width:100%;padding:10px;background:#7ec8e3;color:#000;border:none;border-radius:4px;cursor:pointer;font-weight:bold">
      Sign in
    </button>
  </form>
</div>""", nav=False)


@router.post("/login")
async def login_submit(password: str = Form(...)):
    if check_password(password):
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie(COOKIE_NAME, make_token(), httponly=True, samesite="lax", max_age=86400 * 30)
        return resp
    return RedirectResponse("/dashboard/login?error=1", status_code=303)


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/dashboard/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def overview(mojo_dash: Optional[str] = Cookie(default=None)):
    if redir := _require_auth(mojo_dash):
        return redir

    # Queue stats
    tasks_data = _load_json(_mem("scheduler_tasks.json"), {"tasks": {}})
    tasks = list(tasks_data.get("tasks", {}).values())
    by_status: dict = {}
    for t in tasks:
        s = t.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1

    cards_html = ""
    for status, count in sorted(by_status.items()):
        cards_html += f'<div class="card"><div class="num">{count}</div><div class="lbl">{status}</div></div>'

    # Recent events (last 40, level ≥ 1)
    events = _load_json(_mem("events.json"), [])
    recent = [e for e in reversed(events) if e.get("hitl_level", 0) >= 1][:40]

    rows = ""
    for e in recent:
        lvl = e.get("hitl_level", 0)
        rows += f"""<tr>
          <td class="lvl{lvl}">{lvl}</td>
          <td>{_ts(e.get('timestamp'))}</td>
          <td>{e.get('event_type','')}</td>
          <td>{e.get('title') or e.get('message','')[:120]}</td>
        </tr>"""

    # Recently active tasks
    active = sorted(
        [t for t in tasks if t.get("status") in ("running", "waiting_for_input", "completed")],
        key=lambda t: t.get("completed_at") or t.get("started_at") or "",
        reverse=True
    )[:8]

    task_rows = ""
    for t in active:
        task_rows += f"""<tr>
          <td><a href="/dashboard/tasks/{t['id']}">{t['id']}</a></td>
          <td>{_badge(t.get('status','?'))}</td>
          <td>{t.get('config',{}).get('role_id','—')}</td>
          <td>{_ago(t.get('completed_at') or t.get('started_at'))}</td>
          <td style="color:#888;max-width:300px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">
            {str(t.get('config',{}).get('goal',''))[:100]}
          </td>
        </tr>"""

    return _page("Overview", f"""
<h1>Overview</h1>
<div class="cards">{cards_html}</div>

<h2>Recent Activity</h2>
<table>
  <tr><th>Lvl</th><th>Time</th><th>Type</th><th>Title</th></tr>
  {rows}
</table>

<h2>Recent Tasks</h2>
<table>
  <tr><th>ID</th><th>Status</th><th>Role</th><th>When</th><th>Goal</th></tr>
  {task_rows}
</table>
""")


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@router.get("/tasks", response_class=HTMLResponse)
async def tasks_list(status: str = "", mojo_dash: Optional[str] = Cookie(default=None)):
    if redir := _require_auth(mojo_dash):
        return redir

    tasks_data = _load_json(_mem("scheduler_tasks.json"), {"tasks": {}})
    tasks = list(tasks_data.get("tasks", {}).values())

    all_statuses = sorted({t.get("status", "unknown") for t in tasks})
    filtered = [t for t in tasks if not status or t.get("status") == status]
    filtered.sort(key=lambda t: t.get("created_at", ""), reverse=True)

    filter_links = '<a href="/dashboard/tasks" class="' + ("active" if not status else "") + '">all</a>'
    for s in all_statuses:
        active = "active" if s == status else ""
        filter_links += f'<a href="/dashboard/tasks?status={s}" class="{active}">{s}</a>'

    rows = ""
    for t in filtered:
        cfg = t.get("config", {})
        result = t.get("result") or {}
        metrics = result.get("metrics", {})
        iters = metrics.get("iterations", "—")
        dur = metrics.get("duration_seconds")
        dur_str = f"{dur:.0f}s" if dur else "—"
        rows += f"""<tr>
          <td><a href="/dashboard/tasks/{t['id']}">{t['id']}</a></td>
          <td>{_badge(t.get('status','?'))}</td>
          <td>{cfg.get('role_id','—')}</td>
          <td>{t.get('priority','')}</td>
          <td>{iters}</td>
          <td>{dur_str}</td>
          <td>{_ts(t.get('created_at'))}</td>
          <td style="max-width:260px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;color:#888">
            {str(cfg.get('goal',''))[:100]}
          </td>
        </tr>"""

    return _page("Tasks", f"""
<h1>Tasks <span style="color:#888;font-size:14px">({len(filtered)} shown)</span></h1>
<div class="filters">{filter_links}</div>
<table>
  <tr><th>ID</th><th>Status</th><th>Role</th><th>Priority</th><th>Iters</th><th>Duration</th><th>Created</th><th>Goal</th></tr>
  {rows}
</table>
""")


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(task_id: str, mojo_dash: Optional[str] = Cookie(default=None)):
    if redir := _require_auth(mojo_dash):
        return redir

    tasks_data = _load_json(_mem("scheduler_tasks.json"), {"tasks": {}})
    task = tasks_data.get("tasks", {}).get(task_id)
    if not task:
        return _page("Not found", "<p>Task not found.</p>")

    cfg = task.get("config", {})
    result = task.get("result") or {}
    metrics = result.get("metrics", {})

    # Meta table
    def row(k, v):
        return f"<tr><td style='color:#888;width:140px'>{k}</td><td>{v}</td></tr>"

    meta = f"""<table style="margin-bottom:20px">
      {row("Status", _badge(task.get('status','?')))}
      {row("Role", cfg.get('role_id','—'))}
      {row("Priority", task.get('priority','—'))}
      {row("Created", _ts(task.get('created_at')))}
      {row("Started", _ts(task.get('started_at')))}
      {row("Completed", _ts(task.get('completed_at')))}
      {row("Iterations", metrics.get('iterations','—'))}
      {row("Duration", f"{metrics.get('duration_seconds',0):.1f}s" if metrics.get('duration_seconds') else '—')}
      {row("Retry count", task.get('retry_count', 0))}
    </table>"""

    # Goal
    goal_html = f'<h2>Goal</h2><div class="pre">{cfg.get("goal","—")}</div>'

    # Iteration log
    iter_html = ""
    for it in metrics.get("iteration_log", []):
        n = it.get("iteration", "?")
        model = it.get("model", "")
        status = it.get("status", "")
        tools = ", ".join(it.get("tool_calls", [])) or "—"
        elapsed = it.get("elapsed_s", 0)
        css_cls = status if status in ("tool_use", "final", "error") else ""
        iter_html += f"""<div class="iter {css_cls}">
          <b>#{n}</b> &nbsp; {model} &nbsp;
          <span style="color:#888">{status}</span> &nbsp;
          tools: <span style="color:#7ec8e3">{tools}</span> &nbsp;
          <span style="color:#555">{elapsed:.1f}s</span>
        </div>"""

    if iter_html:
        iter_html = f"<h2>Iterations</h2>{iter_html}"

    # Final answer
    final = result.get("final_answer") or metrics.get("final_answer", "")
    final_html = f'<h2>Final Answer</h2><div class="pre">{final}</div>' if final else ""

    # Error
    err = task.get("last_error") or result.get("error_message", "")
    err_html = f'<h2>Error</h2><div class="pre" style="border-color:#e37e7e;color:#e37e7e">{err}</div>' if err else ""

    # Pending question (HITL)
    pq = task.get("pending_question", "")
    pq_html = f'<h2>Waiting for Input</h2><div class="pre" style="border-color:#ffd700">{pq}</div>' if pq else ""

    # Full session transcript
    session_path = _mem("task_sessions", f"{task_id}.json")
    session_html = ""
    session_data = _load_json(session_path)
    if session_data:
        msgs = session_data.get("messages", [])
        turns = []
        for m in msgs:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "system":
                continue
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        btype = block.get("type", "")
                        if btype == "text":
                            text = block.get("text", "")[:2000]
                            turns.append(f'<div class="iter"><b style="color:#aaa">{role}</b><div class="pre" style="margin-top:6px">{text}</div></div>')
                        elif btype == "tool_use":
                            inp = json.dumps(block.get("input", {}), indent=2)[:1000]
                            turns.append(f'<div class="iter tool_use"><b style="color:#7ec8e3">tool_use: {block.get("name","")}</b><div class="pre" style="margin-top:6px">{inp}</div></div>')
            elif isinstance(content, str) and content.strip():
                turns.append(f'<div class="iter"><b style="color:#aaa">{role}</b><div class="pre" style="margin-top:6px">{content[:2000]}</div></div>')
        if turns:
            session_html = f"<h2>Session Transcript</h2>{''.join(turns)}"

    return _page(f"Task: {task_id}", f"""
<h1><a href="/dashboard/tasks" style="color:#888;font-weight:normal">Tasks</a> / {task_id}</h1>
{meta}
{goal_html}
{pq_html}
{err_html}
{iter_html}
{final_html}
{session_html}
""")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@router.get("/events", response_class=HTMLResponse)
async def events_log(level: int = 0, mojo_dash: Optional[str] = Cookie(default=None)):
    if redir := _require_auth(mojo_dash):
        return redir

    events = _load_json(_mem("events.json"), [])
    filtered = [e for e in reversed(events) if e.get("hitl_level", 0) >= level]

    level_links = ""
    for l in range(6):
        active = "active" if l == level else ""
        count = sum(1 for e in events if e.get("hitl_level", 0) == l)
        level_links += f'<a href="/dashboard/events?level={l}" class="{active}">L{l} ({count})</a> '

    rows = ""
    for e in filtered[:200]:
        lvl = e.get("hitl_level", 0)
        etype = e.get("event_type", "")
        title = e.get("title") or e.get("message", "")
        task_id = e.get("task_id", "")
        task_link = f'<a href="/dashboard/tasks/{task_id}">{task_id}</a>' if task_id else "—"
        rows += f"""<tr>
          <td class="lvl{lvl}">{lvl}</td>
          <td style="color:#555">{_ts(e.get('timestamp'))}</td>
          <td style="color:#888">{etype}</td>
          <td>{task_link}</td>
          <td>{title[:160]}</td>
        </tr>"""

    return _page("Events", f"""
<h1>Event Log <span style="color:#888;font-size:14px">(showing L{level}+, last 200)</span></h1>
<div class="filters">{level_links}</div>
<table>
  <tr><th>Lvl</th><th>Time</th><th>Type</th><th>Task</th><th>Title</th></tr>
  {rows}
</table>
""")


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

@router.get("/roles", response_class=HTMLResponse)
async def roles_view(mojo_dash: Optional[str] = Cookie(default=None)):
    if redir := _require_auth(mojo_dash):
        return redir

    roles_dir = _mem("roles")
    role_files = sorted(roles_dir.glob("*.json")) if roles_dir.exists() else []
    tasks_data = _load_json(_mem("scheduler_tasks.json"), {"tasks": {}})
    tasks = list(tasks_data.get("tasks", {}).values())

    rows = ""
    for rf in role_files:
        role = _load_json(rf, {})
        rid = rf.stem
        name = role.get("name", rid)
        agent_type = role.get("agent_type", "—")
        tool_access = ", ".join(role.get("tool_access", []))
        # Count tasks for this role
        role_tasks = [t for t in tasks if t.get("config", {}).get("role_id") == rid]
        completed = sum(1 for t in role_tasks if t.get("status") == "completed")
        failed = sum(1 for t in role_tasks if t.get("status") == "failed")
        # Private memory
        priv_mem = _mem("roles", rid, "knowledge_multi_model.json")
        mem_badge = '<span style="color:#7ec87e">✓</span>' if priv_mem.exists() else '<span style="color:#555">—</span>'

        rows += f"""<tr>
          <td><b>{name}</b><br><span style="color:#555">{rid}</span></td>
          <td>{agent_type}</td>
          <td style="color:#888;font-size:11px">{tool_access}</td>
          <td style="color:#7ec8e3">{completed}</td>
          <td style="color:#e37e7e">{failed}</td>
          <td>{mem_badge}</td>
        </tr>"""

    return _page("Roles", f"""
<h1>Roles</h1>
<table>
  <tr><th>Name / ID</th><th>Type</th><th>Tools</th><th>Completed</th><th>Failed</th><th>Private Memory</th></tr>
  {rows}
</table>
""")
