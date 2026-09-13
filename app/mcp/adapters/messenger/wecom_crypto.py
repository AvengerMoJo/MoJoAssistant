"""WeCom (企业微信) callback crypto — signature verification + AES message codec.

Implements the same algorithm as Tencent's official WXBizMsgCrypt reference
(https://github.com/sbzhu/weworkapi_python, and the equivalent doc at
https://developer.work.weixin.qq.com/document/path/90968). Reimplemented
here (not vendored) to use pycryptodome instead of the deprecated pycrypto,
and to raise typed exceptions instead of numeric ierror codes.

Wire format (all WeCom callback traffic, both the one-time GET URL-verify
handshake and every POST message delivery):
  msg_signature = SHA1(sorted([token, timestamp, nonce, encrypted])) hex digest
    — for the GET verify step, `encrypted` is the `echostr` query param;
    for POST, it is the `<Encrypt>` field's raw base64 text.
  AES key = base64url-decode(encoding_aes_key + "=") -> 32 raw bytes
  IV = AES key's first 16 bytes (WeCom-specific: no separate IV is sent)
  Plaintext layout after AES-CBC decrypt + PKCS7 unpad:
    16 random bytes | 4-byte big-endian content length | content | corp_id
  Padding block size is 32 bytes (not the usual 16) — this is a WeCom/
  WeChat-specific deviation from standard PKCS7, matched here exactly so
  ciphertext produced/consumed here round-trips with real WeCom servers.
"""

from __future__ import annotations

import base64
import hashlib
import os
import struct
from typing import Tuple

from Crypto.Cipher import AES

_PKCS7_BLOCK_SIZE = 32


class WeComCryptoError(Exception):
    """Signature mismatch, bad padding, or malformed ciphertext."""


def _pkcs7_pad(data: bytes) -> bytes:
    pad_len = _PKCS7_BLOCK_SIZE - (len(data) % _PKCS7_BLOCK_SIZE)
    if pad_len == 0:
        pad_len = _PKCS7_BLOCK_SIZE
    return data + bytes([pad_len]) * pad_len


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise WeComCryptoError("empty plaintext after AES decrypt")
    pad_len = data[-1]
    if pad_len < 1 or pad_len > _PKCS7_BLOCK_SIZE or pad_len > len(data):
        raise WeComCryptoError("invalid PKCS7 padding")
    return data[:-pad_len]


class WeComCrypto:
    """Verifies and (de)codes one corp app's encrypted callback traffic."""

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str) -> None:
        if len(encoding_aes_key) != 43:
            raise ValueError("encoding_aes_key must be exactly 43 characters")
        self._token = token
        self._corp_id = corp_id
        self._key = base64.b64decode(encoding_aes_key + "=")
        self._iv = self._key[:16]

    # ------------------------------------------------------------------
    # Signature
    # ------------------------------------------------------------------

    def _signature(self, timestamp: str, nonce: str, encrypted: str) -> str:
        parts = sorted([self._token, timestamp, nonce, encrypted])
        return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()

    def verify_signature(
        self, msg_signature: str, timestamp: str, nonce: str, encrypted: str
    ) -> None:
        expected = self._signature(timestamp, nonce, encrypted)
        # Not a secret-comparison in the HMAC sense (SHA1 over public-ish
        # inputs), but constant-time compare costs nothing here.
        import hmac as _hmac

        if not _hmac.compare_digest(expected, msg_signature):
            raise WeComCryptoError("msg_signature mismatch")

    # ------------------------------------------------------------------
    # Decrypt
    # ------------------------------------------------------------------

    def _aes_decrypt(self, encrypted_b64: str) -> bytes:
        cipher = AES.new(self._key, AES.MODE_CBC, self._iv)
        raw = cipher.decrypt(base64.b64decode(encrypted_b64))
        return _pkcs7_unpad(raw)

    def _unwrap(self, plaintext: bytes) -> str:
        if len(plaintext) < 20:
            raise WeComCryptoError("decrypted payload too short")
        content_len = struct.unpack(">I", plaintext[16:20])[0]
        content = plaintext[20 : 20 + content_len]
        received_corp_id = plaintext[20 + content_len :].decode("utf-8")
        if received_corp_id != self._corp_id:
            raise WeComCryptoError(
                f"corp_id mismatch in decrypted payload: got {received_corp_id!r}"
            )
        return content.decode("utf-8")

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        """One-time GET handshake. Returns the plaintext to echo back verbatim."""
        self.verify_signature(msg_signature, timestamp, nonce, echostr)
        return self._unwrap(self._aes_decrypt(echostr))

    def decrypt_message(
        self, msg_signature: str, timestamp: str, nonce: str, encrypted: str
    ) -> str:
        """POST callback. `encrypted` is the <Encrypt> field's text. Returns
        the decrypted inner XML message string."""
        self.verify_signature(msg_signature, timestamp, nonce, encrypted)
        return self._unwrap(self._aes_decrypt(encrypted))

    # ------------------------------------------------------------------
    # Encrypt (for reply payloads, if we ever answer synchronously)
    # ------------------------------------------------------------------

    def encrypt_message(
        self, reply_plaintext: str, timestamp: str, nonce: str
    ) -> Tuple[str, str]:
        """Returns (encrypted_b64, msg_signature) for `reply_plaintext`."""
        random16 = os.urandom(16)
        content = reply_plaintext.encode("utf-8")
        length_prefix = struct.pack(">I", len(content))
        payload = random16 + length_prefix + content + self._corp_id.encode("utf-8")
        cipher = AES.new(self._key, AES.MODE_CBC, self._iv)
        encrypted_b64 = base64.b64encode(cipher.encrypt(_pkcs7_pad(payload))).decode("utf-8")
        signature = self._signature(timestamp, nonce, encrypted_b64)
        return encrypted_b64, signature
