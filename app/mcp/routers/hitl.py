"""
HITL (Human-in-the-loop) Reply Router

Provides a lightweight endpoint for replying to WAITING_FOR_INPUT tasks.
Used by ntfy action buttons — NOT part of the dashboard (dashboard is read-only).

Routes:
  GET  /api/hitl/reply/{task_id}?token=<hmac>  — minimal HTML reply form
  POST /api/hitl/reply/{task_id}?token=<hmac>  — submit reply (form or plain text body)

Auth: HMAC-signed token scoped to the task_id.
  Token = HMAC-SHA256(secret, "hitl_reply:{task_id}")
  Embed in ntfy action URLs so tapping a button is one step.

MOJO_BASE_URL env var (e.g. "https://mojo.example.com") is required for
ntfy action buttons to include the correct URL. If unset, the view-form
action is omitted from notifications.
"""

import base64
import hashlib
import hmac
import html
import os
from typing import Any, Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter(prefix="/api/hitl")

_scheduler: Optional[Any] = None


def set_scheduler(scheduler: Any) -> None:
    global _scheduler
    _scheduler = scheduler


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def _secret() -> str:
    return os.getenv("MCP_API_KEY") or os.getenv("DASHBOARD_PASSWORD") or "changeme"


def make_reply_token(task_id: str) -> str:
    """Return an HMAC token scoped to this task_id."""
    msg = f"hitl_reply:{task_id}".encode()
    sig = hmac.new(_secret().encode(), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode()


def _verify(task_id: str, token: str | None) -> bool:
    if not token:
        return False
    try:
        return hmac.compare_digest(token, make_reply_token(task_id))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/reply/{task_id}", response_class=HTMLResponse)
async def reply_form(task_id: str, token: str = ""):
    if not _verify(task_id, token):
        return HTMLResponse("<h2>Invalid or expired link.</h2>", status_code=403)

    safe_id = html.escape(task_id)
    safe_token = html.escape(token)

    # Load pending question from scheduler if available
    question_html = ""
    if _scheduler:
        task = _scheduler.queue.get(task_id)
        if task and task.pending_question:
            q = html.escape(task.pending_question)
            question_html = f'<div style="background:#1a1a1a;border:1px solid #ffd700;border-radius:4px;padding:12px;margin-bottom:16px;font-size:14px;white-space:pre-wrap">{q}</div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reply to {safe_id}</title>
<style>
  body{{background:#111;color:#e0e0e0;font-family:monospace;padding:20px;max-width:600px;margin:0 auto}}
  h2{{color:#ffd700;margin-bottom:16px}}
  textarea{{width:100%;box-sizing:border-box;background:#1a1a1a;color:#e0e0e0;border:1px solid #444;
            border-radius:4px;padding:10px;font-family:monospace;font-size:14px;resize:vertical}}
  button{{margin-top:10px;background:#ffd700;color:#111;border:none;border-radius:4px;
          padding:10px 24px;font-family:monospace;font-size:14px;cursor:pointer;width:100%}}
</style>
</head><body>
<h2>Reply to task {safe_id}</h2>
{question_html}
<form method="post" action="/api/hitl/reply/{safe_id}?token={safe_token}">
  <textarea name="reply" rows="5" placeholder="Type your reply…" autofocus required></textarea>
  <button type="submit">Send Reply</button>
</form>
</body></html>""")


@router.post("/reply/{task_id}", response_class=HTMLResponse)
async def submit_reply(
    task_id: str,
    token: str = "",
    request: Request = None,
    reply: Optional[str] = Form(default=None),
):
    if not _verify(task_id, token):
        return HTMLResponse("<h2>Invalid or expired link.</h2>", status_code=403)

    # Accept reply from: form field, or raw text body (ntfy http action)
    if reply is None:
        body_bytes = await request.body()
        reply = body_bytes.decode("utf-8", errors="replace").strip()

    if not reply:
        return HTMLResponse("<p>Empty reply — nothing sent.</p>", status_code=400)

    if _scheduler is None:
        return HTMLResponse("<p>Scheduler unavailable.</p>", status_code=503)

    result = _scheduler.resume_task_with_reply(task_id, reply)
    if not result.get("success"):
        err = html.escape(result.get("error", "unknown error"))
        return HTMLResponse(f"<p>Error: {err}</p>", status_code=400)

    # Browser form → friendly confirmation page
    # ntfy http action → 200 JSON (ntfy ignores body)
    accept = (request.headers.get("accept", "") if request else "") or ""
    if "text/html" in accept:
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Replied</title>
<style>body{{background:#111;color:#e0e0e0;font-family:monospace;padding:20px;text-align:center}}</style>
</head><body>
<h2 style="color:#7ec87e">Reply sent ✓</h2>
<p>Task <b>{html.escape(task_id)}</b> has been resumed.</p>
</body></html>""")
    return JSONResponse({"success": True, "task_id": task_id})
