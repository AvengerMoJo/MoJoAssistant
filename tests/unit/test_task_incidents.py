import json

from app.scheduler.task_incidents import classify, last_tool, record_incident


def test_oversized_request_is_a_context_overflow_even_when_the_provider_only_says_400():
    assert classify("Client error '400 Bad Request' for url x", 383_573, 128_000) == "context_overflow"


def test_other_kinds():
    assert classify("HTTP 429 Too Many Requests", 1000, 128_000) == "rate_limit"
    assert classify("Client error '400 Bad Request'", 1000, 128_000) == "provider_4xx"
    assert classify("403 Forbidden", None, None) == "auth"
    assert classify("ReadTimeout timed out", None, None) == "timeout"
    assert classify("weird", None, None) == "unknown"


def test_incident_row_has_sizes_and_last_tool_but_no_content(tmp_path):
    log = [{"iteration": 1, "tool_calls": ["web_search"]}, {"iteration": 2, "tool_calls": ["playwright__browser_evaluate"]}]
    p = tmp_path / "i.jsonl"
    row = record_incident("t1", "scott", "glm_5_2", "400 Bad Request", 12, 383_573, 128_000, 1_500_000, log, path=p)
    saved = json.loads(p.read_text())
    assert saved == row and row["kind"] == "context_overflow" and row["last_tool"] == "playwright__browser_evaluate"
    assert last_tool([]) is None
