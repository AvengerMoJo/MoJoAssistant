"""
MoJoAssistant Dashboard — monitoring UI + role chat.

Routes:
  GET  /dashboard/login            — login form
  POST /dashboard/login            — authenticate
  GET  /dashboard/logout           — clear session
  GET  /dashboard                  — overview (queue stats + recent events)
  GET  /dashboard/tasks            — task list
  GET  /dashboard/tasks/{id}       — task detail + session transcript
  GET  /dashboard/events           — full event log
  GET  /dashboard/roles            — roles overview
  GET  /dashboard/chat             — list roles available for chat
  GET  /dashboard/chat/{role_id}         — chat UI for a role (optional ?session_id=)
  GET  /dashboard/chat/{role_id}/stream  — SSE stream: ?message=&session_id=
  POST /dashboard/chat/{role_id}         — send message, redirect back (non-JS fallback)
"""

import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

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
  <a href="/dashboard/chat">Chat</a>
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
/* Chat UI */
.chat-layout { display: flex; gap: 16px; height: calc(100vh - 140px); min-height: 500px; }
.chat-sidebar { width: 220px; flex-shrink: 0; overflow-y: auto; }
.chat-sidebar h2 { margin-top: 0; }
.session-link { display: block; padding: 7px 10px; border-radius: 4px; color: #888; font-size: 11px; margin-bottom: 4px; border: 1px solid transparent; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.session-link:hover { background: #1a1a1a; color: #d4d4d4; text-decoration: none; }
.session-link.active { background: #1a1a2a; border-color: #7ec8e3; color: #7ec8e3; }
.new-chat-btn { display: block; padding: 7px 10px; border-radius: 4px; background: #1a2a1a; border: 1px solid #3a3a3a; color: #7ec87e; font-size: 11px; text-align: center; margin-bottom: 12px; cursor: pointer; }
.new-chat-btn:hover { background: #1e3a1e; text-decoration: none; }
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.chat-history { flex: 1; overflow-y: auto; padding: 10px 0; margin-bottom: 12px; }
.chat-bubble { margin: 8px 0; display: flex; flex-direction: column; }
.chat-bubble.user { align-items: flex-end; }
.chat-bubble.assistant { align-items: flex-start; }
.bubble-label { font-size: 10px; color: #555; margin-bottom: 3px; text-transform: uppercase; letter-spacing: 0.5px; }
.bubble-text { max-width: 80%; padding: 10px 14px; border-radius: 8px; white-space: pre-wrap; word-break: break-word; line-height: 1.6; font-size: 12px; }
.chat-bubble.user .bubble-text { background: #1a2a3a; border: 1px solid #2a4a6a; color: #b0d8f0; }
.chat-bubble.assistant .bubble-text { background: #1a1a1a; border: 1px solid #333; color: #d4d4d4; }
.chat-input-area { display: flex; gap: 8px; border-top: 1px solid #333; padding-top: 12px; flex-shrink: 0; }
.chat-input-area textarea { flex: 1; background: #1a1a1a; border: 1px solid #444; color: #d4d4d4; border-radius: 4px; padding: 10px; font-family: inherit; font-size: 13px; resize: vertical; min-height: 72px; }
.chat-input-area textarea:focus { outline: none; border-color: #7ec8e3; }
.chat-send-btn { padding: 10px 18px; background: #7ec8e3; color: #000; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; font-family: inherit; align-self: flex-end; }
.chat-send-btn:hover { background: #a0d8f0; }
.chat-send-btn:disabled { background: #333; color: #666; cursor: not-allowed; }
.chat-meta { font-size: 10px; color: #555; margin-top: 3px; }
.role-card { background: #1a1a1a; border: 1px solid #333; border-radius: 6px; padding: 16px 20px; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between; }
.role-card .role-name { font-size: 15px; color: #fff; }
.role-card .role-id { font-size: 11px; color: #555; margin-top: 2px; }
.role-card .chat-link { padding: 6px 14px; background: #1a2a3a; border: 1px solid #2a4a6a; border-radius: 4px; color: #7ec8e3; font-size: 12px; }
.role-card .chat-link:hover { background: #1e3a4e; text-decoration: none; }
.empty-chat { color: #555; text-align: center; padding: 40px 0; font-size: 12px; }
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

    parent_id = task.get("parent_task_id")
    parent_link = f'<a href="/dashboard/tasks/{parent_id}">{parent_id}</a>' if parent_id else "—"
    depth = task.get("dispatch_depth", 0)
    depth_label = f"{depth}" + (" (sub-task)" if depth > 0 else "")

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
      {row("Dispatched by", parent_link)}
      {row("Dispatch depth", depth_label)}
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
    pq_html = f'<h2>Waiting for Input</h2><div class="pre" style="border-color:#ffd700">{html.escape(pq)}</div>' if pq else ""

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
                            text = html.escape(block.get("text", "")[:2000])
                            turns.append(f'<div class="iter"><b style="color:#aaa">{html.escape(role)}</b><div class="pre" style="margin-top:6px">{text}</div></div>')
                        elif btype == "tool_use":
                            inp = html.escape(json.dumps(block.get("input", {}), indent=2)[:1000])
                            turns.append(f'<div class="iter tool_use"><b style="color:#7ec8e3">tool_use: {html.escape(block.get("name",""))}</b><div class="pre" style="margin-top:6px">{inp}</div></div>')
            elif isinstance(content, str) and content.strip():
                turns.append(f'<div class="iter"><b style="color:#aaa">{html.escape(role)}</b><div class="pre" style="margin-top:6px">{html.escape(content[:2000])}</div></div>')
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


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def _get_resource_manager():
    """Try to create a ResourceManager from config. Returns None on failure."""
    try:
        from app.scheduler.resource_pool import ResourceManager
        import logging
        return ResourceManager(logger=logging.getLogger(__name__))
    except Exception:
        return None


@router.get("/chat", response_class=HTMLResponse)
async def chat_list(mojo_dash: Optional[str] = Cookie(default=None)):
    if redir := _require_auth(mojo_dash):
        return redir

    roles_dir = _mem("roles")
    role_files = sorted(roles_dir.glob("*.json")) if roles_dir.exists() else []

    cards_html = ""
    for rf in role_files:
        role = _load_json(rf, {})
        rid = rf.stem
        name = role.get("name", rid)
        agent_type = role.get("agent_type", "")
        type_label = f'<span style="color:#555;font-size:11px">{html.escape(agent_type)}</span>' if agent_type else ""
        # Count past sessions
        session_dir = _mem("roles", rid, "chat_history")
        session_count = len(list(session_dir.glob("*.json"))) if session_dir.exists() else 0
        session_label = f'{session_count} session{"s" if session_count != 1 else ""}' if session_count else "no sessions yet"
        cards_html += f"""
<div class="role-card">
  <div>
    <div class="role-name">{html.escape(name)}</div>
    <div class="role-id">{html.escape(rid)} &nbsp;·&nbsp; {type_label} &nbsp;·&nbsp; <span style="color:#555">{session_label}</span></div>
  </div>
  <a href="/dashboard/chat/{html.escape(rid)}" class="chat-link">Open Chat →</a>
</div>"""

    if not cards_html:
        cards_html = '<p style="color:#555">No roles found in memory. Check ~/.memory/roles/</p>'

    return _page("Chat", f"""
<h1>Chat with Assistants</h1>
<p style="color:#555;margin-bottom:20px;font-size:12px">
  Direct conversation — read-only window into each assistant's knowledge and personality.
  To assign new work, use <code style="color:#7ec8e3">scheduler_add_task</code> via MoJo.
</p>
{cards_html}
""")


@router.get("/chat/{role_id}", response_class=HTMLResponse)
async def chat_view(
    role_id: str,
    session_id: Optional[str] = None,
    mojo_dash: Optional[str] = Cookie(default=None),
):
    if redir := _require_auth(mojo_dash):
        return redir

    from app.scheduler.role_chat import list_chat_sessions

    role_file = _mem("roles", f"{role_id}.json")
    role = _load_json(role_file, {})
    role_name = role.get("name", role_id) if role else role_id

    # Load session list
    sessions = list_chat_sessions(role_id)

    # Determine active session.
    # No session_id in URL = new chat (blank slate, form submits to a fresh session).
    # Explicit session_id in URL = load that session's history.
    active_session_id = session_id  # None when "+ New Chat" or first visit
    exchanges: list = []

    if active_session_id:
        session_file = _mem("roles", role_id, "chat_history", f"{active_session_id}.json")
        session_data = _load_json(session_file, {})
        exchanges = session_data.get("exchanges", [])
    # No else — no session_id means new chat; exchanges stays empty, form_session stays ""

    # Sidebar: session list
    new_chat_active = " active" if active_session_id is None else ""
    sidebar_html = f'<h2>Sessions</h2><a href="/dashboard/chat/{html.escape(role_id)}" class="new-chat-btn{new_chat_active}">+ New Chat</a>'
    for s in sessions:
        sid = s.get("session_id", "")
        turns = s.get("turn_count", 0)
        last = _ago(s.get("last_active"))
        css = "active" if sid == active_session_id else ""
        label = f'{last} · {turns} turn{"s" if turns != 1 else ""}'
        sidebar_html += f'<a href="/dashboard/chat/{html.escape(role_id)}?session_id={html.escape(sid)}" class="session-link {css}" title="{html.escape(sid)}">{html.escape(label)}</a>'

    if not sessions:
        sidebar_html += '<div style="color:#555;font-size:11px;padding:6px 0">No sessions yet</div>'

    # Chat history bubbles
    bubbles_html = ""
    for ex in exchanges:
        user_text = html.escape(ex.get("user", ""))
        asst_text = html.escape(ex.get("assistant", ""))
        ts = _ts(ex.get("timestamp"))
        bubbles_html += f"""
<div class="chat-bubble user">
  <div class="bubble-label">you</div>
  <div class="bubble-text">{user_text}</div>
  <div class="chat-meta">{ts}</div>
</div>
<div class="chat-bubble assistant">
  <div class="bubble-label">{html.escape(role_name)}</div>
  <div class="bubble-text">{asst_text}</div>
</div>"""

    if not bubbles_html:
        if active_session_id:
            bubbles_html = f'<div class="empty-chat">No messages in this session yet. Say something to {html.escape(role_name)}.</div>'
        else:
            bubbles_html = f'<div class="empty-chat">New conversation with {html.escape(role_name)}. Your first message starts the session.</div>'

    # Session id for form: empty string = new session (auto-generated on first POST)
    form_session = active_session_id or ""

    return _page(f"Chat — {role_name}", f"""
<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:16px">
  <h1><a href="/dashboard/chat" style="color:#888;font-weight:normal">Chat</a> / {html.escape(role_name)}</h1>
  <span style="color:#555;font-size:11px">read-only · no task assignments accepted</span>
</div>
<div class="chat-layout">
  <div class="chat-sidebar">
    {sidebar_html}
  </div>
  <div class="chat-main">
    <div class="chat-history" id="chat-history">
      {bubbles_html}
    </div>
    <div class="chat-input-area">
      <textarea id="msg-input" placeholder="Message {html.escape(role_name)}… (Ctrl+Enter to send)" autofocus></textarea>
      <button class="chat-send-btn" id="send-btn" onclick="sendMessage()">Send</button>
    </div>
  </div>
</div>
<script>
  const ROLE_ID    = {json.dumps(role_id)};
  const ROLE_NAME  = {json.dumps(role_name)};
  let   sessionId  = {json.dumps(form_session)};

  const chatLog  = document.getElementById('chat-history');
  const input    = document.getElementById('msg-input');
  const sendBtn  = document.getElementById('send-btn');

  // Scroll to bottom helper
  function scrollDown() {{ chatLog.scrollTop = chatLog.scrollHeight; }}
  scrollDown();

  // Ctrl+Enter sends
  input.addEventListener('keydown', e => {{
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {{ e.preventDefault(); sendMessage(); }}
  }});

  function appendBubble(role, text, meta) {{
    const wrap = document.createElement('div');
    wrap.className = 'chat-bubble ' + role;
    const label = document.createElement('div');
    label.className = 'bubble-label';
    label.textContent = role === 'user' ? 'you' : ROLE_NAME;
    const bubble = document.createElement('div');
    bubble.className = 'bubble-text';
    bubble.textContent = text;
    wrap.appendChild(label);
    wrap.appendChild(bubble);
    if (meta) {{
      const m = document.createElement('div');
      m.className = 'chat-meta';
      m.textContent = meta;
      wrap.appendChild(m);
    }}
    chatLog.appendChild(wrap);
    scrollDown();
    return bubble;
  }}

  function appendToolStatus(name) {{
    const el = document.createElement('div');
    el.className = 'chat-meta';
    el.style.paddingLeft = '8px';
    el.textContent = '⚙ ' + name + '…';
    chatLog.appendChild(el);
    scrollDown();
    return el;
  }}

  async function sendMessage() {{
    const msg = input.value.trim();
    if (!msg) return;

    input.value = '';
    sendBtn.disabled = true;
    sendBtn.textContent = '…';

    // Show user bubble immediately
    appendBubble('user', msg, new Date().toLocaleTimeString());

    // Placeholder for assistant response
    const asstBubble = appendBubble('assistant', '', null);
    asstBubble.textContent = '';
    asstBubble.style.color = '#555';
    asstBubble.textContent = 'thinking…';

    const params = new URLSearchParams({{ message: msg, session_id: sessionId }});
    const url = '/dashboard/chat/' + encodeURIComponent(ROLE_ID) + '/stream?' + params;

    let toolIndicator = null;
    let responseText  = '';
    let streaming     = false;

    try {{
      const resp = await fetch(url);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);

      const reader = resp.body.getReader();
      const dec    = new TextDecoder();
      let   buf    = '';

      while (true) {{
        const {{ done, value }} = await reader.read();
        if (done) break;
        buf += dec.decode(value, {{ stream: true }});

        // Process complete SSE lines
        let nl;
        while ((nl = buf.indexOf('\\n\\n')) !== -1) {{
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 2);
          if (!line.startsWith('data:')) continue;
          let evt;
          try {{ evt = JSON.parse(line.slice(5).trim()); }} catch {{ continue; }}

          if (evt.type === 'tool') {{
            if (!toolIndicator) {{
              if (toolIndicator) toolIndicator.remove();
            }}
            if (toolIndicator) toolIndicator.remove();
            toolIndicator = appendToolStatus(evt.name);
            asstBubble.style.color = '#555';
            asstBubble.textContent = 'searching…';

          }} else if (evt.type === 'token') {{
            if (!streaming) {{
              if (toolIndicator) {{ toolIndicator.remove(); toolIndicator = null; }}
              asstBubble.style.color = '';
              asstBubble.textContent = '';
              streaming = true;
            }}
            responseText += evt.text;
            asstBubble.textContent = responseText;
            scrollDown();

          }} else if (evt.type === 'done') {{
            if (toolIndicator) {{ toolIndicator.remove(); toolIndicator = null; }}
            if (!responseText) asstBubble.textContent = '(no response)';
            if (evt.session_id) {{
              sessionId = evt.session_id;
              // Update URL without reload so Back button works
              const newUrl = '/dashboard/chat/' + encodeURIComponent(ROLE_ID) + '?session_id=' + encodeURIComponent(evt.session_id);
              history.replaceState(null, '', newUrl);
            }}
          }} else if (evt.type === 'error') {{
            asstBubble.style.color = '#c44';
            asstBubble.textContent = evt.message || '(error)';
          }}
        }}
      }}
    }} catch (err) {{
      asstBubble.style.color = '#c44';
      asstBubble.textContent = 'Error: ' + err.message;
    }}

    sendBtn.disabled = false;
    sendBtn.textContent = 'Send';
    input.focus();
  }}
</script>
""")


@router.get("/chat/{role_id}/stream")
async def chat_stream(
    role_id: str,
    message: str = Query(...),
    session_id: str = Query(default=""),
    mojo_dash: Optional[str] = Cookie(default=None),
):
    """SSE endpoint — streams the role's reply token-by-token."""
    if _require_auth(mojo_dash):
        async def _auth_error():
            yield 'data: {"type":"error","message":"Not authenticated"}\n\n'
        return StreamingResponse(_auth_error(), media_type="text/event-stream")

    from app.scheduler.role_chat import RoleChatSession

    message = message.strip()
    if not message:
        async def _empty():
            yield 'data: {"type":"error","message":"Empty message"}\n\n'
        return StreamingResponse(_empty(), media_type="text/event-stream")

    session = RoleChatSession(role_id=role_id, session_id=session_id or None)
    rm = _get_resource_manager()

    return StreamingResponse(
        session.exchange_stream(message=message, resource_manager=rm),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if behind a proxy
        },
    )


@router.post("/chat/{role_id}")
async def chat_send(
    role_id: str,
    message: str = Form(...),
    session_id: str = Form(default=""),
    mojo_dash: Optional[str] = Cookie(default=None),
):
    if redir := _require_auth(mojo_dash):
        return redir

    from app.scheduler.role_chat import RoleChatSession

    message = message.strip()
    if not message:
        sid = session_id or ""
        return RedirectResponse(
            f"/dashboard/chat/{role_id}" + (f"?session_id={sid}" if sid else ""),
            status_code=303,
        )

    session = RoleChatSession(role_id=role_id, session_id=session_id or None)
    rm = _get_resource_manager()
    await session.exchange(message=message, resource_manager=rm)

    return RedirectResponse(
        f"/dashboard/chat/{role_id}?session_id={session.session_id}",
        status_code=303,
    )
