"""Long-running coding jobs: a third-party agent (OpenCode) works in its own sandbox
clone on its own branch while a checker watches it.  Spec:
~/.memory/research/specs/popo_long_running_job_spec.md

One job = one file ~/.memory/jobs/<job_id>.json.  The launcher creates it and returns at
once; the checker (every few minutes) gathers facts, classifies the job by rules, answers
safe permission prompts, and only for a non-running job asks the reviewer (Paul).
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.config.paths import get_memory_path

POPO_KEY = "~/.ssh/popo_ai_github"
PORT_RANGE = (4700, 4799)
DEFAULT_MODEL = {"providerID": "minimax-coding-plan", "id": "MiniMax-M3.1-Flash"}
DEFAULT_BUDGET = {"max_hours": 6, "max_steps": 300}
CONTRACT = ("goal", "done_when", "out_of_scope", "verify_by", "repo")
LIVE_STATES = {"running", "stalled", "blocked"}
STALL_MIN = 60
CHECK_REVIEW_GAP_MIN = 30
MAX_CONTINUES = 3
MAX_REPLANS = 2
# Permission prompts the checker answers once without asking anybody.
SAFE_COMMANDS = ("git ", "pytest", "python", "venv/bin/python", "ls", "cat ", "grep ", "rg ", "find ", "head ", "tail ")


class JobError(Exception):
    pass


def jobs_dir() -> Path:
    d = Path(get_memory_path()) / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_job(job_id: str) -> Dict[str, Any]:
    p = jobs_dir() / f"{job_id}.json"
    if not p.exists():
        raise JobError(f"no such job: {job_id}")
    return json.loads(p.read_text())


def save_job(job: Dict[str, Any]) -> None:
    p = jobs_dir() / f"{job['job_id']}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2))
    os.chmod(tmp, 0o600)  # holds the per-job server password
    tmp.replace(p)
    json.loads(p.read_text())  # read back: the file must parse


def list_jobs(states=None) -> List[Dict[str, Any]]:
    out = []
    for p in sorted(jobs_dir().glob("*.json")):
        job = json.loads(p.read_text())
        if states is None or job.get("state") in states:
            out.append(job)
    return out


def validate_spec(spec: Dict[str, Any]) -> None:
    missing = [k for k in CONTRACT if not str(spec.get(k, "")).strip()]
    if missing:
        raise JobError(f"job spec lacks {missing}: a goal needs Done when / Out of scope / Verify by and a repo")
    if not re.fullmatch(r"[a-z0-9_]{3,40}", spec.get("job_id", "")):
        raise JobError("job_id must be 3-40 chars of a-z 0-9 _")


def _run(cmd: List[str], env: Optional[dict] = None, cwd: Optional[str] = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env={**os.environ, **(env or {})}, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _git(sandbox: str, *args: str, timeout: int = 60) -> str:
    r = _run(["git", "-C", sandbox, *args], timeout=timeout)
    if r.returncode != 0:
        raise JobError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r.stdout


class OcClient:
    """The few OpenCode v2 HTTP calls a job needs."""

    def __init__(self, port: int, password: str) -> None:
        auth = base64.b64encode(f"opencode:{password}".encode()).decode()
        self._c = httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"Authorization": f"Basic {auth}"}, timeout=30)

    def _j(self, method: str, path: str, **kw: Any) -> Any:
        r = self._c.request(method, path, **kw)
        r.raise_for_status()
        body = r.json() if r.content else None
        return body["data"] if isinstance(body, dict) and "data" in body else body

    def active(self) -> Any: return self._j("GET", "/api/session/active")
    def create_session(self) -> dict: return self._j("POST", "/api/session", json={})
    def set_model(self, sid: str, model: dict) -> Any:
        return self._j("POST", f"/api/session/{sid}/model", json={"model": {"id": model["id"], "providerID": model["providerID"]}})
    def prompt(self, sid: str, text: str) -> Any: return self._j("POST", f"/api/session/{sid}/prompt", json={"text": text})
    def messages(self, sid: str) -> list: return self._j("GET", f"/api/session/{sid}/message", params={"limit": 200}) or []
    def permissions(self, sid: str) -> list: return self._j("GET", f"/api/session/{sid}/permission") or []
    def reply_permission(self, sid: str, pid: str, decision: str) -> Any:
        return self._j("POST", f"/api/session/{sid}/permission/{pid}/reply", json={"decision": decision})
    def forms(self, sid: str) -> list: return self._j("GET", f"/api/session/{sid}/form") or []
    def close(self) -> None: self._c.close()


def client_for(job: Dict[str, Any]) -> OcClient:
    return OcClient(job["port"], job["password"])


def contract_prompt(job: Dict[str, Any]) -> str:
    return f"""You are working alone on a coding job. Nobody will answer questions while you work.

GOAL: {job['goal']}
DONE WHEN: {job['done_when']}
OUT OF SCOPE: {job['out_of_scope']}
VERIFY BY: {job['verify_by']}

Rules:
- Work only inside this directory (a clone of {job['repo']}), on branch {job['branch']}. Never touch other directories.
- Commit small and often. Push only branch {job['branch']} (git push origin {job['branch']}). Never merge, never force-push, never delete branches.
- Commit as the repository owner; do NOT add Co-Authored-By lines.
- Keep STATUS.md in the repo root up to date after each milestone: done so far, next step, blockers, how you checked your work. Do not commit STATUS.md.
- Use the project's test command and make it pass before you finish.
- When finished: push the branch and open a pull request against main with `gh pr create` (title, body, test result).
  If `gh pr create` fails, write the full text to PR.md and say so in STATUS.md.
- Last line of STATUS.md must be `JOB_RESULT: DONE` when the goal is met, or `JOB_RESULT: BLOCKED <why>` when you cannot continue.
- Do not ask questions. If something is unclear, choose the safest reading, write it in STATUS.md, and go on.
"""


def launch(spec: Dict[str, Any], *, sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    """Create sandbox + branch + server + session, send the contract, record the job, return."""
    validate_spec(spec)
    job_id = spec["job_id"]
    if (jobs_dir() / f"{job_id}.json").exists():
        raise JobError(f"job {job_id} already exists")
    live_same_repo = [j["job_id"] for j in list_jobs(LIVE_STATES) if j["repo"] == spec["repo"]]
    if live_same_repo:
        raise JobError(f"one live job per repo: {live_same_repo} is still running on {spec['repo']}")

    sandbox = str(Path(get_memory_path()) / "sandboxes" / f"job_{job_id}")
    branch = f"wip_{job_id}"
    key = os.path.expanduser(POPO_KEY)
    ssh = {"GIT_SSH_COMMAND": f"ssh -i {shlex.quote(key)} -o IdentitiesOnly=yes"}
    r = _run(["git", "clone", spec["repo"], sandbox], env=ssh, timeout=600)
    if r.returncode != 0:
        raise JobError(f"git clone failed: {r.stderr.strip()[:300]}")
    _git(sandbox, "checkout", "-b", branch)
    # Push and `gh` from inside the sandbox use Popo's own key.
    _git(sandbox, "config", "core.sshCommand", ssh["GIT_SSH_COMMAND"].replace("GIT_SSH_COMMAND=", ""))
    with open(os.path.join(sandbox, ".git", "info", "exclude"), "a") as f:
        f.write("STATUS.md\nPR.md\n")

    port = _free_port()
    password = secrets.token_hex(16)
    unit = f"mojo-job-{job_id}"
    r = _run(["systemd-run", "--user", f"--unit={unit}", "-E", f"OPENCODE_SERVER_PASSWORD={password}",
              f"--working-directory={sandbox}", os.path.expanduser("~/.bun/bin/opencode"),
              "serve", "--hostname", "127.0.0.1", "--port", str(port)])
    if r.returncode != 0:
        raise JobError(f"could not start the OpenCode server: {r.stderr.strip()[:300]}")

    job: Dict[str, Any] = {
        "job_id": job_id, "goal": spec["goal"], "done_when": spec["done_when"],
        "out_of_scope": spec["out_of_scope"], "verify_by": spec["verify_by"],
        "repo": spec["repo"], "base_branch": spec.get("base_branch", "main"), "branch": branch,
        "sandbox_path": sandbox, "unit": unit, "port": port, "password": password,
        "session_id": None, "model": spec.get("model") or DEFAULT_MODEL,
        "budget": {**DEFAULT_BUDGET, **(spec.get("budget") or {})},
        "started_at": now_iso(), "state": "running", "last_check_at": None,
        "continues": 0, "checks": [],
    }
    save_job(job)  # recorded before the session exists so a half-started job is still visible
    oc = client_for(job)
    try:
        for _ in range(30):  # the server needs a few seconds
            try:
                oc.active()
                break
            except Exception:
                sleep(2)
        else:
            raise JobError("OpenCode server did not come up in 60 s")
        sid = oc.create_session()["id"]
        oc.set_model(sid, job["model"])
        oc.prompt(sid, contract_prompt(job))
        job["session_id"] = sid
        save_job(job)
    except Exception as e:
        job["state"] = "dead"
        job["checks"].append({"at": now_iso(), "state": "dead", "reason": f"launch failed: {e}"})
        save_job(job)
        stop_server(job)
        raise
    finally:
        oc.close()
    return job


def _free_port() -> int:
    import socket
    used = {j["port"] for j in list_jobs() if j.get("port")}
    for p in range(PORT_RANGE[0], PORT_RANGE[1] + 1):
        if p in used:
            continue
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise JobError("no free port in 4700-4799")


def stop_server(job: Dict[str, Any]) -> None:
    _run(["systemctl", "--user", "stop", job["unit"]])


# ---------------------------------------------------------------- facts


def read_status_md(job: Dict[str, Any]) -> str:
    p = Path(job["sandbox_path"]) / "STATUS.md"
    return p.read_text()[-4000:] if p.exists() else ""


def job_result_line(status_md: str) -> Optional[str]:
    for line in reversed(status_md.strip().splitlines()):
        if line.startswith("JOB_RESULT:"):
            return line.strip()
    return None


def collect_facts(job: Dict[str, Any], oc: Optional[OcClient] = None) -> Dict[str, Any]:
    """Everything the classifier needs.  No model call."""
    own = oc is None
    oc = oc or client_for(job)
    facts: Dict[str, Any] = {"server_up": False, "session_active": False, "minutes_idle": None,
                             "commits": 0, "minutes_since_commit": None, "pr_url": None,
                             "status_md": read_status_md(job), "pending_permissions": [], "pending_forms": 0}
    facts["job_result"] = job_result_line(facts["status_md"])
    started = datetime.fromisoformat(job["started_at"])
    facts["hours_running"] = round((datetime.now(timezone.utc) - started).total_seconds() / 3600, 2)
    sandbox = job["sandbox_path"]
    try:
        facts["commits"] = int(_git(sandbox, "rev-list", "--count", f"origin/{job['base_branch']}..HEAD").strip() or 0)
        last = _git(sandbox, "log", "-1", "--format=%ct").strip()
        if last and facts["commits"]:
            facts["minutes_since_commit"] = int((time.time() - int(last)) / 60)
        facts["diff_stat"] = _git(sandbox, "diff", "--stat", f"origin/{job['base_branch']}..HEAD")[-1500:]
    except JobError as e:
        facts["git_error"] = str(e)
    try:
        facts["server_up"] = True
        active = oc.active()
        facts["session_active"] = bool(job.get("session_id")) and job["session_id"] in (active if isinstance(active, (dict, list)) else [])
        msgs = oc.messages(job["session_id"]) if job.get("session_id") else []
        created = [m.get("time", {}).get("created", 0) for m in msgs]
        if created:
            facts["minutes_idle"] = int(time.time() - max(created) / 1000) // 60 if max(created) > 1e12 else int(time.time() - max(created)) // 60
        facts["steps"] = sum(1 for m in msgs if m.get("type") == "assistant")
        facts["pending_permissions"] = oc.permissions(job["session_id"]) if job.get("session_id") else []
        facts["pending_forms"] = len(oc.forms(job["session_id"])) if job.get("session_id") else 0
    except Exception as e:
        facts["server_up"] = False
        facts["server_error"] = str(e)[:200]
    facts["pr_url"] = _find_pr(job)
    if own:
        oc.close()
    return facts


def _find_pr(job: Dict[str, Any]) -> Optional[str]:
    r = _run(["gh", "pr", "list", "--head", job["branch"], "--json", "url", "--limit", "1"], cwd=job["sandbox_path"], timeout=30)
    if r.returncode != 0:
        return None
    try:
        rows = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return rows[0]["url"] if rows else None


# ---------------------------------------------------------------- rules


def classify(job: Dict[str, Any], facts: Dict[str, Any]) -> str:
    """State from facts alone.  Order matters: the most final reading wins."""
    b = job["budget"]
    if facts["hours_running"] > b["max_hours"] or facts.get("steps", 0) > b["max_steps"]:
        return "over_budget"
    result = facts["job_result"] or ""
    if result.startswith("JOB_RESULT: DONE") and facts["pr_url"]:
        return "done"
    if result.startswith("JOB_RESULT: BLOCKED") or facts["pending_forms"]:
        return "blocked"
    if not facts["server_up"] or (job.get("session_id") is None):
        return "dead"
    if result.startswith("JOB_RESULT: DONE") and not facts["pr_url"]:
        return "blocked"  # claims done but no PR: Paul decides (token problem or agent gave up)
    if facts["pending_permissions"]:
        return "running"  # handled by auto_permissions; unanswerable ones become blocked there
    idle = facts["minutes_idle"]
    recent_commit = facts["minutes_since_commit"] is not None and facts["minutes_since_commit"] < STALL_MIN
    if not facts["session_active"] and (idle is None or idle >= 10) and not recent_commit:
        return "stalled"
    if idle is not None and idle >= STALL_MIN and not recent_commit:
        return "stalled"
    return "running"


def permission_is_safe(perm: Dict[str, Any], sandbox: str) -> bool:
    """A prompt the checker may answer 'once': every resource is inside the sandbox
    or a plain read/test/git command."""
    resources = perm.get("resources") or []
    if not resources:
        return False
    for res in resources:
        res = str(res)
        if res.startswith("/"):
            if not os.path.abspath(res).startswith(os.path.abspath(sandbox).rstrip("/") + "/") and os.path.abspath(res) != os.path.abspath(sandbox):
                return False
        elif not res.startswith(SAFE_COMMANDS):
            return False
        if re.search(r"(\.ssh|\.env|\.gnupg|\.aws|id_rsa|credential|vault)", res):
            return False
    return True


def auto_permissions(job: Dict[str, Any], facts: Dict[str, Any], oc: OcClient) -> List[Dict[str, Any]]:
    """Answer safe prompts; return the ones that need a human decision."""
    unanswered = []
    for perm in facts["pending_permissions"]:
        if permission_is_safe(perm, job["sandbox_path"]):
            oc.reply_permission(job["session_id"], perm["id"], "once")
        else:
            unanswered.append(perm)
    return unanswered


# ---------------------------------------------------------------- review


DECISIONS = ("CONTINUE", "STATUS_UP", "DONE", "REPLAN", "ASK_OWNER")


def review_prompt(job: Dict[str, Any], facts: Dict[str, Any], state: str, unanswered: list) -> str:
    return f"""You are Paul, the product manager, reviewing a coding job that works alone. You judge at the level of the plan, not the code.
A rule check found the job in state: {state}.

GOAL: {job['goal']}
DONE WHEN: {job['done_when']}
OUT OF SCOPE: {job['out_of_scope']}
VERIFY BY: {job['verify_by']}

FACTS: hours running {facts['hours_running']} of {job['budget']['max_hours']}; steps {facts.get('steps')}; commits {facts['commits']};
minutes since last commit {facts['minutes_since_commit']}; minutes idle {facts['minutes_idle']}; session active {facts['session_active']};
pull request {facts['pr_url']}; consecutive CONTINUEs already sent {job['continues']}.
Permission prompts waiting that the checker could not answer: {json.dumps(unanswered)[:600]}
DIFF STAT:
{facts.get('diff_stat', '')}
STATUS.md (the agent's own report):
{facts['status_md']}

Decide whether the assistant is stuck or stopped for a wrong reason. Answer with ONE JSON object and nothing else:
{{"decision": "CONTINUE|STATUS_UP|DONE|REPLAN|ASK_OWNER", "reason": "one or two sentences", "message": "for CONTINUE: the exact instruction to send the agent; for STATUS_UP/ASK_OWNER/REPLAN: what the owner needs to read; else empty"}}
CONTINUE = the stop was wrong, tell it what to do next. STATUS_UP = real but slow progress, tell the owner briefly. DONE = the goal is met and a PR exists.
REPLAN = this approach is failing, give a revised plan in message. ASK_OWNER = only if a decision truly needs the owner and you cannot make it from the facts; say what you would choose."""


def parse_decision(text: str) -> Dict[str, str]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise JobError(f"reviewer gave no JSON: {text[:200]!r}")
    d = json.loads(m.group(0))
    if d.get("decision") not in DECISIONS:
        raise JobError(f"reviewer decision not one of {DECISIONS}: {d.get('decision')!r}")
    return {"decision": d["decision"], "reason": str(d.get("reason", "")), "message": str(d.get("message", ""))}


def log_decision(job: Dict[str, Any], state: str, decision: Dict[str, str]) -> None:
    """Every Paul decision, for Bonsai to rate later (owner_feedback is filled in by the owner or Bonsai)."""
    p = Path(get_memory_path()) / "state" / "job_decisions.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": now_iso(), "job_id": job["job_id"], "state_at_review": state, **decision,
           "continues_before": job["continues"], "owner_feedback": None}
    with p.open("a") as f:
        f.write(json.dumps(row) + "\n")


def apply_decision(job: Dict[str, Any], decision: Dict[str, str], oc: OcClient) -> str:
    """Carry out the decision.  Returns the notice for the owner, or '' for none."""
    d = decision["decision"]
    if d == "CONTINUE":
        if job["continues"] >= MAX_CONTINUES:
            job["state"] = "blocked"
            return f"Job {job['job_id']}: {MAX_CONTINUES} nudges did not move it. {decision['reason']}"
        oc.prompt(job["session_id"], decision["message"] or "Carry on with the next step. Do not stop until the goal's Done-when is met.")
        job["continues"] += 1
        job["state"] = "running"
        return ""
    job["continues"] = 0
    if d == "STATUS_UP":
        job["state"] = "running"
        return f"Job {job['job_id']} status: {decision['message'] or decision['reason']}"
    if d == "DONE":
        job["state"] = "done"
        return f"Job {job['job_id']} is done. {decision['reason']}"
    if d == "REPLAN":
        job["replans"] = job.get("replans", 0) + 1
        if job["replans"] > MAX_REPLANS or not decision["message"].strip():
            job["state"] = "blocked"
            return f"Job {job['job_id']} failed {MAX_REPLANS} replans: {decision['reason']}"
        oc.prompt(job["session_id"], "The plan changed. New plan, follow it from here:\n" + decision["message"])
        job["state"] = "running"
        return f"Job {job['job_id']} was re-planned by Paul (replan {job['replans']}): {decision['reason']}"
    job["state"] = "blocked"
    return f"Job {job['job_id']} needs you: {decision['message'] or decision['reason']}"
