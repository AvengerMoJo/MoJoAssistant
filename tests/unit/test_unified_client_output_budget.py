"""The shared LLM client must leave a thinking model room for its answer.

2026-10-09: _build_payload capped every call at min(4096, output_limit). A thinking model (Ornith)
spent all 4096 tokens reasoning and returned content '' (finish_reason=length) -- visible in
dreaming, and a likely contributor to 'iteration budget exhausted without FINAL_ANSWER' elsewhere.
"""
import unittest

from app.llm.unified_client import UnifiedLLMClient

MSGS = [{"role": "user", "content": "hi"}]


class TestOutputBudget(unittest.TestCase):
    def test_resource_output_limit_is_honoured_up_to_the_default_cap(self):
        p = UnifiedLLMClient._build_payload(MSGS, "m", 32000, "openai")
        self.assertEqual(p["max_tokens"], 16000)
        p = UnifiedLLMClient._build_payload(MSGS, "m", 8192, "openai")
        self.assertEqual(p["max_tokens"], 8192)

    def test_cap_is_configurable(self):
        self.assertEqual(UnifiedLLMClient._build_payload(MSGS, "m", 32000, "openai", max_tokens_cap=30000)["max_tokens"], 30000)
        self.assertEqual(UnifiedLLMClient._build_payload(MSGS, "m", 32000, "openai", max_tokens_cap=2000)["max_tokens"], 2000)

    def test_small_resources_are_never_pushed_above_their_own_limit(self):
        self.assertEqual(UnifiedLLMClient._build_payload(MSGS, "m", 1024, "openai", max_tokens_cap=16000)["max_tokens"], 1024)

    def test_anthropic_format_is_unchanged(self):
        self.assertEqual(UnifiedLLMClient._build_payload(MSGS, "m", 32000, "anthropic")["max_tokens"], 2048)


if __name__ == "__main__":
    unittest.main()
