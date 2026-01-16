"""
PKCE (Proof Key for Code Exchange) utilities for OAuth 2.1
Implements RFC 7636 with S256 challenge method
"""
import base64
import hashlib
import secrets
import string
from typing import Tuple


def generate_code_verifier(length: int = 128) -> str:
    """
    Generate a random code verifier for PKCE

    Args:
        length: Length of the verifier (43-128 characters, default: 128)

    Returns:
        Random code verifier string

    Raises:
        ValueError: If length is not in valid range
    """
    if not 43 <= length <= 128:
        raise ValueError("Code verifier length must be between 43 and 128 characters")

    # RFC 7636: code_verifier = unreserved characters (A-Z, a-z, 0-9, -, ., _, ~)
    alphabet = string.ascii_letters + string.digits + "-._~"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_code_challenge(code_verifier: str, method: str = "S256") -> str:
    """
    Generate a code challenge from a code verifier

    Args:
        code_verifier: The code verifier string
        method: Challenge method ("S256" or "plain", default: "S256")

    Returns:
        Code challenge string

    Raises:
        ValueError: If method is not supported
    """
    if method == "S256":
        # SHA256 hash and base64url encode
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return challenge
    elif method == "plain":
        # Plain method (not recommended, but supported for compatibility)
        return code_verifier
    else:
        raise ValueError(f"Unsupported code challenge method: {method}")


def verify_code_challenge(
    code_verifier: str,
    code_challenge: str,
    code_challenge_method: str = "S256"
) -> bool:
    """
    Verify that a code verifier matches the code challenge

    Args:
        code_verifier: The code verifier provided by the client
        code_challenge: The original code challenge
        code_challenge_method: Challenge method used ("S256" or "plain")

    Returns:
        True if verification succeeds, False otherwise
    """
    try:
        computed_challenge = generate_code_challenge(code_verifier, code_challenge_method)
        return computed_challenge == code_challenge
    except Exception:
        return False


def generate_pkce_pair(length: int = 128) -> Tuple[str, str]:
    """
    Generate a complete PKCE code verifier and challenge pair

    Args:
        length: Length of the code verifier (43-128 characters)

    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    verifier = generate_code_verifier(length)
    challenge = generate_code_challenge(verifier, "S256")
    return verifier, challenge


def is_valid_code_verifier(code_verifier: str) -> bool:
    """
    Validate that a code verifier meets RFC 7636 requirements

    Args:
        code_verifier: The code verifier to validate

    Returns:
        True if valid, False otherwise
    """
    # Check length (43-128 characters)
    if not 43 <= len(code_verifier) <= 128:
        return False

    # Check character set (unreserved: A-Z, a-z, 0-9, -, ., _, ~)
    allowed_chars = set(string.ascii_letters + string.digits + "-._~")
    return all(c in allowed_chars for c in code_verifier)
