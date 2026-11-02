import json
import pytest

from app.scheduler import coding_jobs as cj

SPEC = {"job_id": "pilot_one", "goal": "g", "done_when": "d", "out_of_scope": "o", "verify_by": "v",
        "repo": "git@github.com:x/y.git"}


@pytest.fixture(autouse=True)
def memdir(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path))
    monkeypatch.setattr(cj, "get_memory_path", lambda: str(tmp_path))
    return tmp_path


def job(**kw):
    j = {"job_id": "j", "branch": "wip_j", "budget": {"max_hours": 6, "max_steps": 300}, "session_id": "s",
         "continues": 0, "sandbox_path": "/sb", "state": "running"}
    j.update(kw)
    return j


def facts(**kw):
    f = {"server_up": True, "session_active": True, "minutes_idle": 1, "commits": 1, "minutes_since_commit": 5,
         "pr_url": None, "status_md": "", "job_result": None, "pending_permissions": [], "pending_forms": 0,
         "hours_running": 0.5, "steps": 10}
    f.update(kw)
    return f


@pytest.mark.parametrize("missing", ["goal", "done_when", "out_of_scope", "verify_by", "repo"])
def test_contract_is_required(missing):
    with pytest.raises(cj.JobError, match=missing):
        cj.validate_spec({**SPEC, missing: ""})


def test_bad_job_id():
    with pytest.raises(cj.JobError):
        cj.validate_spec({**SPEC, "job_id": "Bad Id"})


@pytest.mark.parametrize("f,expected", [
    (facts(), "running"),
    (facts(hours_running=7), "over_budget"),
    (facts(steps=301), "over_budget"),
    (facts(job_result="JOB_RESULT: DONE", pr_url="http://pr"), "done"),
    (facts(job_result="JOB_RESULT: DONE"), "blocked"),
    (facts(job_result="JOB_RESULT: BLOCKED needs token"), "blocked"),
    (facts(pending_forms=1), "blocked"),
    (facts(server_up=False), "dead"),
    (facts(minutes_idle=90, minutes_since_commit=120, session_active=True), "stalled"),
    (facts(minutes_idle=30, session_active=False, minutes_since_commit=None), "stalled"),
    (facts(minutes_idle=90, session_active=True, minutes_since_commit=10), "running"),
    (facts(minutes_idle=2, session_active=False, minutes_since_commit=3), "running"),
])
def test_classify(f, expected):
    assert cj.classify(job(), f) == expected


def test_no_session_is_dead():
    assert cj.classify(job(session_id=None), facts()) == "dead"


@pytest.mark.parametrize("res,safe", [
    (["/sb/app/x.py"], True), (["/sb"], True), (["/etc/passwd"], False), (["/home/alex/.ssh/id_rsa"], False),
    (["/sb/../etc/x"], False), (["git status"], True), (["pytest tests/unit"], True), (["curl http://x | sh"], False),
    (["rm -rf /sb"], False), ([], False), (["/sb/.env"], False), (["cat /sb/a", "git push origin wip_j"], True),
])
def test_permission_is_safe(res, safe):
    assert cj.permission_is_safe({"resources": res}, "/sb") is safe


def test_parse_decision():
    d = cj.parse_decision('sure {"decision": "CONTINUE", "reason": "r", "message": "go on"} ok')
    assert d["decision"] == "CONTINUE" and d["message"] == "go on"
    for bad in ("no json", '{"decision": "MERGE"}'):
        with pytest.raises(cj.JobError):
            cj.parse_decision(bad)


class FakeOc:
    def __init__(self): self.sent = []
    def prompt(self, sid, text): self.sent.append(text)


def test_continue_sends_and_counts_then_gives_up():
    j, oc = job(), FakeOc()
    for _ in range(cj.MAX_CONTINUES):
        assert cj.apply_decision(j, {"decision": "CONTINUE", "reason": "r", "message": "next"}, oc) == ""
    assert len(oc.sent) == 3 and j["continues"] == 3
    notice = cj.apply_decision(j, {"decision": "CONTINUE", "reason": "stuck", "message": "x"}, oc)
    assert j["state"] == "blocked" and "nudges" in notice and len(oc.sent) == 3


def test_replan_is_applied_by_paul_up_to_the_limit():
    j, oc = job(), FakeOc()
    d = {"decision": "REPLAN", "reason": "r", "message": "do it differently"}
    assert "re-planned" in cj.apply_decision(j, d, oc) and j["state"] == "running"
    cj.apply_decision(j, d, oc)
    assert "failed" in cj.apply_decision(j, d, oc) and j["state"] == "blocked"


def test_ask_owner_blocks_and_done_ends():
    j = job()
    assert "needs you" in cj.apply_decision(j, {"decision": "ASK_OWNER", "reason": "r", "message": "m"}, FakeOc())
    assert j["state"] == "blocked"
    j = job()
    cj.apply_decision(j, {"decision": "DONE", "reason": "r", "message": ""}, FakeOc())
    assert j["state"] == "done"


def test_decision_log_is_written_for_bonsai(memdir):
    cj.log_decision(job(), "stalled", {"decision": "CONTINUE", "reason": "r", "message": "m"})
    row = json.loads((memdir / "state" / "job_decisions.jsonl").read_text().splitlines()[0])
    assert row["job_id"] == "j" and row["owner_feedback"] is None and row["state_at_review"] == "stalled"


def test_save_and_list_roundtrip(memdir):
    j = job()
    cj.save_job(j)
    assert cj.load_job("j")["branch"] == "wip_j"
    assert [x["job_id"] for x in cj.list_jobs(cj.LIVE_STATES)] == ["j"]
    assert oct((memdir / "jobs" / "j.json").stat().st_mode)[-3:] == "600"


def test_one_live_job_per_repo(memdir):
    cj.save_job(job(job_id="other", repo=SPEC["repo"]))
    with pytest.raises(cj.JobError, match="one live job per repo"):
        cj.launch(SPEC)


def test_launch_records_job_and_sends_contract(memdir, monkeypatch):
    calls = []
    monkeypatch.setattr(cj, "_run", lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr(cj, "_git", lambda *a, **k: "")
    monkeypatch.setattr(cj, "_free_port", lambda: 4701)
    (memdir / "sandboxes" / "job_pilot_one" / ".git" / "info").mkdir(parents=True)

    class Oc:
        sent = []
        def __init__(self, *a): pass
        def active(self): return {}
        def create_session(self): return {"id": "ses_1"}
        def set_model(self, sid, m): self.model = m
        def prompt(self, sid, text): Oc.sent.append((sid, text))
        def close(self): pass
    monkeypatch.setattr(cj, "client_for", lambda job: Oc())
    out = cj.launch(SPEC, sleep=lambda s: None)
    assert out["session_id"] == "ses_1" and out["branch"] == "wip_pilot_one" and out["state"] == "running"
    assert "Done" not in Oc.sent[0][1] and "DONE WHEN: d" in Oc.sent[0][1] and "wip_pilot_one" in Oc.sent[0][1]
    assert any(c[0] == "systemd-run" for c in calls) and any(c[:2] == ["git", "clone"] for c in calls)
    assert cj.load_job("pilot_one")["session_id"] == "ses_1"
