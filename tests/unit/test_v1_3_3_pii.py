"""
Unit tests for the PII Scanner (v1.3.3).

Covers:
  - scan_text      (pattern-based PII detection)
  - scan_tool_args (tool argument scanning)
  - redact_pii     (PII replacement with [REDACTED])
"""

import unittest

from app.scheduler.security.pii_scanner import (
    PIIClassificationResult,
    PIIMatch,
    redact_pii,
    scan_text,
    scan_tool_args,
)


class TestScanText(unittest.TestCase):

    def test_returns_no_pii_for_clean_text(self):
        result = scan_text("Hello, this is a normal message about programming.")
        self.assertFalse(result.has_pii)
        self.assertEqual(len(result.matches), 0)
        self.assertEqual(result.summary, "")

    def test_returns_empty_for_short_text(self):
        result = scan_text("hi")
        self.assertFalse(result.has_pii)

    def test_detects_email(self):
        result = scan_text("Contact me at john.doe@example.com for details.")
        self.assertTrue(result.has_pii)
        self.assertIn("pii", result.categories)
        self.assertTrue(any(m.pii_type == "email" for m in result.matches))

    def test_detects_phone_number(self):
        result = scan_text("Call me at (555) 123-4567 or +1-555-987-6543.")
        self.assertTrue(result.has_pii)
        self.assertIn("pii", result.categories)

    def test_detects_ssn(self):
        result = scan_text("My SSN is 123-45-6789.")
        self.assertTrue(result.has_pii)
        self.assertTrue(any(m.pii_type == "ssn" for m in result.matches))

    def test_detects_credit_card(self):
        result = scan_text("Card number: 4111111111111111")
        self.assertTrue(result.has_pii)
        self.assertIn("financial", result.categories)

    def test_detects_api_key(self):
        result = scan_text("API key: sk-abc123def456ghi789jkl012mno345pqr678stu901")
        self.assertTrue(result.has_pii)
        self.assertIn("credentials", result.categories)

    def test_detects_aws_key(self):
        result = scan_text("AWS key: AKIAIOSFODNN7EXAMPLE")
        self.assertTrue(result.has_pii)
        self.assertTrue(any(m.pii_type == "aws_key" for m in result.matches))

    def test_detects_private_key_header(self):
        result = scan_text("-----BEGIN RSA PRIVATE KEY-----")
        self.assertTrue(result.has_pii)
        self.assertTrue(any(m.pii_type == "private_key_header" for m in result.matches))

    def test_detects_password_assignment(self):
        result = scan_text("password: mysecretpassword123")
        self.assertTrue(result.has_pii)
        self.assertTrue(any(m.pii_type == "password_assignment" for m in result.matches))

    def test_detects_ip_address(self):
        result = scan_text("Server at 192.168.1.100 is down.")
        self.assertTrue(result.has_pii)
        self.assertIn("infrastructure", result.categories)

    def test_detects_crypto_wallet(self):
        result = scan_text("Send to 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18")
        self.assertTrue(result.has_pii)
        self.assertIn("financial", result.categories)

    def test_detects_multiple_pii_types(self):
        text = "Email: test@example.com, SSN: 123-45-6789, IP: 10.0.0.1"
        result = scan_text(text)
        self.assertTrue(result.has_pii)
        self.assertGreaterEqual(len(result.matches), 3)
        self.assertIn("pii", result.categories)
        self.assertIn("infrastructure", result.categories)

    def test_redacted_value_preserves_length(self):
        result = scan_text("My email is verylongemail@example.com")
        for match in result.matches:
            if match.pii_type == "email":
                # Redacted value should have asterisks
                self.assertIn("*", match.value)


class TestScanToolArgs(unittest.TestCase):

    def test_scans_dict_args(self):
        args = {"content": "My API key is sk-abc123def456ghi789jkl012mno345pqr678stu901vwx234"}
        result = scan_tool_args("write_file", args)
        # The content contains an API key pattern
        self.assertTrue(result.has_pii)
        self.assertTrue(any(m.category == "credentials" for m in result.matches))

    def test_returns_no_pii_for_safe_args(self):
        args = {"query": "hello world", "limit": 5}
        result = scan_tool_args("memory_search", args)
        self.assertFalse(result.has_pii)


class TestRedactPii(unittest.TestCase):

    def test_returns_original_text_when_no_pii(self):
        text = "Hello, this is a normal message."
        result = redact_pii(text)
        self.assertEqual(result, text)

    def test_redacts_email(self):
        text = "Contact john@example.com for info."
        result = redact_pii(text)
        self.assertNotIn("john@example.com", result)
        self.assertIn("[REDACTED:email]", result)

    def test_redacts_ssn(self):
        text = "SSN: 123-45-6789"
        result = redact_pii(text)
        self.assertNotIn("123-45-6789", result)
        self.assertIn("[REDACTED:ssn]", result)

    def test_redacts_multiple_pii(self):
        text = "Email: test@example.com, SSN: 123-45-6789"
        result = redact_pii(text)
        self.assertNotIn("test@example.com", result)
        self.assertNotIn("123-45-6789", result)
        self.assertIn("[REDACTED:email]", result)
        self.assertIn("[REDACTED:ssn]", result)

    def test_redacts_only_specified_categories(self):
        text = "Email: test@example.com, IP: 192.168.1.1"
        result = redact_pii(text, categories={"pii"})
        self.assertIn("[REDACTED:email]", result)
        # IP is infrastructure, should not be redacted
        self.assertIn("192.168.1.1", result)

    def test_preserves_surrounding_text(self):
        text = "Send to john@example.com and wait."
        result = redact_pii(text)
        self.assertTrue(result.startswith("Send to "))
        self.assertTrue(result.endswith(" and wait."))


if __name__ == "__main__":
    unittest.main()
