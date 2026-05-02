"""
PII Scanner — pattern-based sensitive data detection.

Scans text for PII, credentials, financial data, and health data.
Used by the policy pipeline to flag or block sensitive data before
it crosses a boundary (external LLM call, MCP tool, etc.).

Classification categories:
  - pii: names, emails, phone numbers, SSNs, addresses
  - credentials: API keys, passwords, tokens, private keys
  - financial: credit cards, bank accounts, crypto wallets
  - health: medical records, prescriptions, diagnoses
  - infrastructure: IPs, URLs with auth, internal hostnames

Not a replacement for careful design — a safety net.
"""
# [mojo-integration]

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import ipaddress


@dataclass
class PIIMatch:
    """A single PII detection."""
    category: str       # pii, credentials, financial, health, infrastructure
    pii_type: str       # email, ssn, api_key, etc.
    value: str          # redacted preview
    start: int          # position in text
    end: int
    confidence: float   # 0.0-1.0


@dataclass
class PIIClassificationResult:
    """Result of scanning text for PII."""
    has_pii: bool = False
    categories: Set[str] = field(default_factory=set)
    matches: List[PIIMatch] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_pii": self.has_pii,
            "categories": sorted(self.categories),
            "match_count": len(self.matches),
            "summary": self.summary,
        }


# Compiled patterns for performance
_PATTERNS = {
    "email": (
        "pii",
        re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        0.9,
    ),
    "phone_us": (
        "pii",
        re.compile(r'\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b'),
        0.7,
    ),
    "ssn": (
        "pii",
        re.compile(r'\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b'),
        0.95,
    ),
    "credit_card": (
        "financial",
        re.compile(r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b'),
        0.85,
    ),
    "api_key_generic": (
        "credentials",
        re.compile(r'\b(?:sk|pk|api|key|token|secret|bearer)[_-][A-Za-z0-9]{20,}\b', re.IGNORECASE),
        0.8,
    ),
    "aws_key": (
        "credentials",
        re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
        0.95,
    ),
    "private_key_header": (
        "credentials",
        re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        0.99,
    ),
    "password_assignment": (
        "credentials",
        re.compile(r'(?:password|passwd|pwd|secret)\s*[:=]\s*(?!\$\{)(?!\{\{)(?!<)(?!\[)\S+', re.IGNORECASE),
        0.7,
    ),
    "ip_address": (
        "infrastructure",
        re.compile(r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'),
        0.5,
    ),
    "crypto_wallet": (
        "financial",
        re.compile(r'\b(?:0x[a-fA-F0-9]{40}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[a-zA-HJ-NP-Z0-9]{39,59})\b'),
        0.8,
    ),
    "medical_record": (
        "health",
        re.compile(r'\b(?:MRN|patient.?id|medical.?record|diagnosis|prescription|medication)\s*[:=]?\s*\S+', re.IGNORECASE),
        0.6,
    ),
}


def scan_text(text: str) -> PIIClassificationResult:
    """Scan text for PII and return classification result.

    Args:
        text: The text to scan.

    Returns:
        PIIClassificationResult with matches and summary.
    """
    result = PIIClassificationResult()

    if not text or len(text) < 10:
        return result

    for name, (category, pattern, confidence) in _PATTERNS.items():
        for match in pattern.finditer(text):
            value = match.group(0)

            # Reduce confidence for private/loopback IPs
            if name == "ip_address":
                try:
                    if ipaddress.ip_address(value).is_private:
                        confidence = 0.1  # Effectively filter out unless threshold lowered
                except ValueError:
                    pass

            # Redact the value for logging
            if len(value) > 8:
                redacted = value[:4] + "*" * (len(value) - 8) + value[-4:]
            else:
                redacted = "*" * len(value)

            result.matches.append(PIIMatch(
                category=category,
                pii_type=name,
                value=redacted,
                start=match.start(),
                end=match.end(),
                confidence=confidence,
            ))
            result.categories.add(category)

    result.has_pii = len(result.matches) > 0
    if result.has_pii:
        cats = sorted(result.categories)
        result.summary = f"Found {len(result.matches)} PII matches in categories: {', '.join(cats)}"

    return result


def scan_tool_args(tool_name: str, args: Dict[str, Any]) -> PIIClassificationResult:
    """Scan tool call arguments for PII.

    Args:
        tool_name: Name of the tool being called.
        args: Tool arguments dict.

    Returns:
        PIIClassificationResult.
    """
    try:
        import json
        text = json.dumps(args, ensure_ascii=False)
    except Exception:
        text = str(args)

    result = scan_text(text)
    return result


def redact_pii(text: str, categories: Optional[Set[str]] = None) -> str:
    """Redact PII from text.

    Args:
        text: Text to redact.
        categories: Only redact these categories (None = all).

    Returns:
        Text with PII replaced by [REDACTED].
    """
    result = scan_text(text)
    if not result.has_pii:
        return text

    # Sort matches by position (reverse) to preserve offsets
    sorted_matches = sorted(result.matches, key=lambda m: m.start, reverse=True)

    redacted = text
    for match in sorted_matches:
        if categories and match.category not in categories:
            continue
        replacement = f"[REDACTED:{match.pii_type}]"
        redacted = redacted[:match.start] + replacement + redacted[match.end:]

    return redacted
