from app.scheduler.run_ledger import classify_error


def test_time_budget_stop_is_a_timeout_not_iteration_exhaustion():
    # 2026-10-09: paul_community_daily stopped at 600s after 2 iterations and was reported as "(2/35)" iterations.
    assert classify_error("Time budget exhausted (627s of 600s) after 2 iterations (max 35) without FINAL_ANSWER.") == "timeout"
    assert classify_error("Iteration budget exhausted (35/35) without FINAL_ANSWER.") == "iteration_budget"
