"""Phase 1 of the BRIDLE learning loop: the incident log must carry the provider's own words,
and the same failure in several tasks must read as one pattern.

What is tested here:
  A. `record_incident` stores the provider's response body (first 500 chars, secrets scrubbed),
     and `extract_response_body` gets it off the raised httpx error.
  B. `repeated_patterns` groups rows by (resource, kind, normalised signature) and only counts
     what is inside the time window and what happened in at least `min_tasks` distinct tasks.
  Rows written before the `response_body` field existed must still load.
"""
import json
import time

import httpx
import pytest

from app.scheduler.task_incidents import (
    RESPONSE_BODY_CHARS,
    classify,
    extract_response_body,
    last_tool,
    load_incidents,
    record_incident,
    repeated_patterns,
    scrub_secrets,
    signature_for,
)


def _row(task_id="t1", resource="glm_5_2", kind="provider_4xx", error="Client error '400 Bad Request' for url x",
         body=None, ts=None, largest=None):
    """One incident row as it is written to the log (raw, so the timestamp can be controlled)."""
    row = {
        "t": time.time() if ts is None else ts,
        "task_id": task_id,
        "role_id": "scott",
        "resource": resource,
        "iteration": 1,
        "kind": kind,
        "error": error,
        "est_input_tokens": 1000,
        "context_limit": 128000,
        "largest_message_chars": largest,
        "last_tool": None,
    }
    if body is not None:
        row["response_body"] = body
    return row


def _append(path, *rows):
    with open(path, "a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


# --------------------------------------------------------------------------------------
# Existing behaviour (kept: the log is a durable record, not a content dump)
# --------------------------------------------------------------------------------------
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


# --------------------------------------------------------------------------------------
# A. the provider's response body
# --------------------------------------------------------------------------------------
def test_the_provider_response_body_is_recorded(tmp_path):
    p = tmp_path / "i.jsonl"
    body = '{"error": {"message": "prompt is too long: 195000 tokens > 163840 maximum", "code": 400}}'
    row = record_incident("t1", "scott", "glm_5_2", "400 Bad Request", 3, 195_000, 163_840, 900_000, [],
                          path=p, response_body=body)
    assert row["response_body"] == body
    assert json.loads(p.read_text())["response_body"] == body


def test_the_response_body_is_cut_to_500_chars(tmp_path):
    p = tmp_path / "i.jsonl"
    row = record_incident("t1", None, "glm_5_2", "400 Bad Request", 1, None, None, None, [],
                          path=p, response_body="x" * 900)
    assert len(row["response_body"]) == RESPONSE_BODY_CHARS


def test_a_row_without_a_body_has_none(tmp_path):
    p = tmp_path / "i.jsonl"
    row = record_incident("t1", None, "glm_5_2", "ReadTimeout", 1, None, None, None, [], path=p)
    assert row["response_body"] is None


@pytest.mark.parametrize("body, secret", [
    ('{"Authorization": "Bearer sk-live-0123456789abcdef"}', "sk-live-0123456789abcdef"),
    ("Authorization: sk-plain-0123456789abcdef", "sk-plain-0123456789abcdef"),
    ('{"api_key": "sk-live-0123456789abcdef"}', "sk-live-0123456789abcdef"),
    ('{"x-api-key": "abc123def456"}', "abc123def456"),
    ("token Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig", "eyJhbGciOiJIUzI1NiJ9.payload.sig"),
    ("https://api.example.com/v1?key=sk-0123456789abcdef&model=x", "sk-0123456789abcdef"),
])
def test_secrets_are_scrubbed_out_of_the_body(body, secret):
    scrubbed = scrub_secrets(body)
    assert secret not in scrubbed
    assert "REDACTED" in scrubbed


def test_scrubbing_keeps_the_message_the_owner_needs():
    body = '{"error": {"message": "invalid api key: sk-live-0123456789abcdef", "code": 401}}'
    scrubbed = scrub_secrets(body)
    assert "invalid api key" in scrubbed and "401" in scrubbed


def test_the_body_is_scrubbed_before_it_is_stored(tmp_path):
    p = tmp_path / "i.jsonl"
    row = record_incident("t1", None, "glm_5_2", "401 Unauthorized", 1, None, None, None, [], path=p,
                          response_body='{"api_key": "sk-live-0123456789abcdef", "error": "invalid key"}')
    assert "sk-live-0123456789abcdef" not in row["response_body"]
    assert "sk-live-0123456789abcdef" not in p.read_text()


def test_the_body_comes_off_the_raised_httpx_error():
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(400, request=request, text='{"error": {"message": "boom", "code": 400}}')
    error = httpx.HTTPStatusError("400 Bad Request", request=request, response=response)
    assert extract_response_body(error) == '{"error": {"message": "boom", "code": 400}}'


def test_a_failure_without_a_response_has_no_body():
    assert extract_response_body(httpx.ReadTimeout("timed out")) is None


# --------------------------------------------------------------------------------------
# B. repeated patterns
# --------------------------------------------------------------------------------------
def test_the_same_failure_in_two_tasks_is_one_pattern(tmp_path):
    p = tmp_path / "i.jsonl"
    body = '{"error": {"message": "prompt is too long: 195000 tokens > 163840 maximum", "code": 400}}'
    _append(p,
            _row(task_id="t1", body=body, largest=900_000),
            _row(task_id="t2", body=body, largest=1_200_000))
    patterns = repeated_patterns(path=p)
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern["resource_id"] == "glm_5_2"
    assert pattern["kind"] == "provider_4xx"
    assert pattern["count"] == 2
    assert pattern["task_count"] == 2
    assert sorted(pattern["example_task_ids"]) == ["t1", "t2"]
    assert pattern["largest_message_chars_min"] == 900_000
    assert pattern["largest_message_chars_max"] == 1_200_000
    assert pattern["status"] == "400"
    assert pattern["first_seen"] and pattern["last_seen"]


def test_one_task_failing_twice_is_not_a_pattern_yet(tmp_path):
    p = tmp_path / "i.jsonl"
    body = '{"error": {"message": "boom", "code": 400}}'
    _append(p, _row(task_id="t1", body=body), _row(task_id="t1", body=body))
    assert repeated_patterns(path=p) == []
    assert len(repeated_patterns(min_tasks=1, path=p)) == 1


def test_a_different_resource_is_a_different_pattern(tmp_path):
    p = tmp_path / "i.jsonl"
    body = '{"error": {"message": "boom", "code": 400}}'
    _append(p,
            _row(task_id="t1", resource="glm_5_2", body=body),
            _row(task_id="t2", resource="glm_5_2", body=body),
            _row(task_id="t3", resource="openrouter_free_x", body=body),
            _row(task_id="t4", resource="openrouter_free_x", body=body))
    patterns = repeated_patterns(path=p)
    assert len(patterns) == 2
    assert {p_["resource_id"] for p_ in patterns} == {"glm_5_2", "openrouter_free_x"}


def test_rows_outside_the_window_are_not_counted(tmp_path):
    p = tmp_path / "i.jsonl"
    body = '{"error": {"message": "boom", "code": 400}}'
    old = time.time() - 30 * 86400
    _append(p,
            _row(task_id="t1", body=body, ts=old),
            _row(task_id="t2", body=body, ts=old),
            _row(task_id="t3", body=body))
    assert repeated_patterns(window_days=14, path=p) == []
    assert len(repeated_patterns(min_tasks=1, window_days=14, path=p)) == 1  # only the fresh row
    # With a wider window the two old rows come back and join the same group.
    wide = repeated_patterns(min_tasks=1, window_days=45, path=p)
    assert len(wide) == 1 and wide[0]["count"] == 3


def test_digits_and_ids_do_not_split_a_pattern(tmp_path):
    p = tmp_path / "i.jsonl"
    _append(p,
            _row(task_id="t1", body='{"error": {"message": "too long: 195000 tokens > 163840 maximum", "code": 400}}'),
            _row(task_id="t2", body='{"error": {"message": "too long: 201111 tokens > 163840 maximum", "code": 400}}'))
    patterns = repeated_patterns(path=p)
    assert len(patterns) == 1
    assert patterns[0]["count"] == 2


def test_a_different_message_is_a_different_pattern(tmp_path):
    p = tmp_path / "i.jsonl"
    _append(p,
            _row(task_id="t1", error="Client error '400 Bad Request' for url x",
                 body='{"error": {"message": "too long: 195000 tokens", "code": 400}}'),
            _row(task_id="t2", error="Client error '400 Bad Request' for url x",
                 body='{"error": {"message": "too long: 201111 tokens", "code": 400}}'),
            _row(task_id="t3", error="Client error '401 Unauthorized' for url x",
                 body='{"error": {"message": "invalid api key", "code": 401}}'),
            _row(task_id="t4", error="Client error '401 Unauthorized' for url x",
                 body='{"error": {"message": "invalid api key", "code": 401}}'))
    patterns = repeated_patterns(path=p)
    assert len(patterns) == 2
    assert {p_["status"] for p_ in patterns} == {"400", "401"}


def test_rows_written_before_the_body_field_still_load_and_still_group(tmp_path):
    """Old rows have no `response_body` key at all -- they must load and fall back to the
    error line, not blow up."""
    p = tmp_path / "i.jsonl"
    _append(p,
            _row(task_id="t1", error="Client error '400 Bad Request' for url x"),
            _row(task_id="t2", error="Client error '400 Bad Request' for url x"))
    rows = load_incidents(p)
    assert len(rows) == 2
    assert "response_body" not in rows[0]
    patterns = repeated_patterns(path=p)
    assert len(patterns) == 1 and patterns[0]["count"] == 2


def test_a_half_written_last_line_is_counted_not_fatal(tmp_path):
    p = tmp_path / "i.jsonl"
    body = '{"error": {"message": "boom", "code": 400}}'
    _append(p, _row(task_id="t1", body=body), _row(task_id="t2", body=body))
    with open(p, "a") as f:
        f.write('{"t": 1.0, "task_id": "t3", "res')  # torn write
    patterns = repeated_patterns(path=p)
    assert len(patterns) == 1 and patterns[0]["count"] == 2


def test_the_signature_is_the_status_plus_the_first_80_normalised_chars():
    row = _row(body='{"error": {"message": "boom", "code": 400}}')
    signature = signature_for(row)
    assert signature.startswith("400|")
    assert len(signature.split("|", 1)[1]) <= 80


def test_the_executor_passes_the_provider_body_into_the_incident_row():
    """The body only reaches the log if the executor hands it over -- check the wiring."""
    import ast
    import inspect

    import app.scheduler.agentic_executor as module

    tree = ast.parse(inspect.getsource(module))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "record_incident"]
    assert calls, "the executor must record incidents"
    assert any(any(kw.arg == "response_body" for kw in call.keywords) for call in calls), \
        "the executor must pass the provider's response body into the incident row"
    assert any(isinstance(n, ast.Name) and n.id == "extract_response_body"
               for n in ast.walk(tree)), "the executor must read the body off the failed call"
