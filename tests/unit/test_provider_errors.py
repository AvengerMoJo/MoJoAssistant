"""
Tests for app.scheduler.provider_errors — the shared classifier extracted
2026-07-30 after a real incident: zai-coding-plan's 5-hour quota exhaustion
was treated identically to a generic connection blip by both
resource_pool.py's circuit breaker and coding_agent_executor.py.
"""

from __future__ import annotations

import time
from datetime import datetime

from app.scheduler.provider_errors import classify_provider_error


class TestClassifyProviderError:
    def test_real_zai_quota_message_classified_and_reset_time_extracted(self):
        msg = (
            "AI_APICallError: Usage limit reached for 5 hour. "
            "Your limit will reset at 2026-07-30 15:04:03"
        )
        category, rate_limited_until = classify_provider_error(msg)
        assert category == "quota_exhausted"
        assert rate_limited_until is not None
        expected = datetime.strptime("2026-07-30 15:04:03", "%Y-%m-%d %H:%M:%S").timestamp()
        assert rate_limited_until == expected

    def test_generic_connection_error_is_not_quota_exhausted(self):
        category, rate_limited_until = classify_provider_error("Connection refused")
        assert category == "external_unavailable"
        assert rate_limited_until is None

    def test_generic_timeout_is_not_quota_exhausted(self):
        category, rate_limited_until = classify_provider_error("Request timeout after 30s")
        assert category == "external_unavailable"
        assert rate_limited_until is None

    def test_quota_message_without_parseable_reset_time_still_classified(self):
        category, rate_limited_until = classify_provider_error("429 quota exceeded")
        assert category == "quota_exhausted"
        assert rate_limited_until is None

    def test_retry_after_seconds_extracted(self):
        before = time.time()
        category, rate_limited_until = classify_provider_error(
            "429 too many requests, retry after 30"
        )
        after = time.time()
        assert category == "quota_exhausted"
        assert rate_limited_until is not None
        assert before + 29 <= rate_limited_until <= after + 31

    def test_missing_resource_still_classified_correctly(self):
        category, rate_limited_until = classify_provider_error("404 not found")
        assert category == "missing_resource"
        assert rate_limited_until is None

    def test_unknown_error_falls_through(self):
        category, rate_limited_until = classify_provider_error("something completely unrelated")
        assert category == "unknown"
        assert rate_limited_until is None

    def test_empty_message(self):
        category, rate_limited_until = classify_provider_error("")
        assert category == "unknown"
        assert rate_limited_until is None
