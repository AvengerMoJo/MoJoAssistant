"""Tests for WeComCrypto (app/mcp/adapters/messenger/wecom_crypto.py).

No live WeCom account exists yet to test against real traffic (corporate
registration is a separate, week(s)-long process — see
project memory), so this validates the implementation two ways:
  1. Algorithm structure matches Tencent's official WXBizMsgCrypt reference
     (32-byte PKCS7 blocks, key=base64url(aes_key+"="), IV=key[:16],
     plaintext = 16 random + 4-byte big-endian length + content + corp_id,
     signature = SHA1(sorted([token, timestamp, nonce, encrypted]))) --
     confirmed against https://github.com/sbzhu/weworkapi_python/blob/master/callback/WXBizMsgCrypt.py
  2. Round-trip: encrypt_message() output must decrypt back to the
     original plaintext via decrypt_message(), and verify_url() must
     reject a tampered signature/echostr.
"""
import base64
import hashlib
import unittest

from app.mcp.adapters.messenger.wecom_crypto import WeComCrypto, WeComCryptoError

# 43-char base64 -> 32 raw bytes once "=" is appended; arbitrary but valid-shaped test key.
_TEST_AES_KEY = "jWmYm7qr5nMoAUwZRjGtBxmz3KA1tkAj3ykkR6q2B2C"
_TEST_TOKEN = "QDG6eK"
_TEST_CORP_ID = "wwtestcorpid0000"


class TestWeComCryptoInit(unittest.TestCase):
    def test_rejects_wrong_length_aes_key(self):
        with self.assertRaises(ValueError):
            WeComCrypto(_TEST_TOKEN, "too-short", _TEST_CORP_ID)

    def test_key_and_iv_derivation(self):
        crypto = WeComCrypto(_TEST_TOKEN, _TEST_AES_KEY, _TEST_CORP_ID)
        expected_key = base64.b64decode(_TEST_AES_KEY + "=")
        self.assertEqual(crypto._key, expected_key)
        self.assertEqual(len(crypto._key), 32)
        self.assertEqual(crypto._iv, expected_key[:16])


class TestSignature(unittest.TestCase):
    def setUp(self):
        self.crypto = WeComCrypto(_TEST_TOKEN, _TEST_AES_KEY, _TEST_CORP_ID)

    def test_signature_matches_manual_sha1_of_sorted_concat(self):
        token, ts, nonce, enc = _TEST_TOKEN, "1476416373", "47744683", "ZmFrZWNpcGhlcnRleHQ="
        expected = hashlib.sha1("".join(sorted([token, ts, nonce, enc])).encode()).hexdigest()
        self.assertEqual(self.crypto._signature(ts, nonce, enc), expected)

    def test_verify_signature_accepts_correct(self):
        ts, nonce, enc = "123", "456", "abc"
        sig = self.crypto._signature(ts, nonce, enc)
        self.crypto.verify_signature(sig, ts, nonce, enc)  # should not raise

    def test_verify_signature_rejects_tampered(self):
        ts, nonce, enc = "123", "456", "abc"
        sig = self.crypto._signature(ts, nonce, enc)
        with self.assertRaises(WeComCryptoError):
            self.crypto.verify_signature(sig, ts, nonce, "tampered")


class TestEncryptDecryptRoundTrip(unittest.TestCase):
    def setUp(self):
        self.crypto = WeComCrypto(_TEST_TOKEN, _TEST_AES_KEY, _TEST_CORP_ID)

    def test_round_trip_recovers_plaintext(self):
        plaintext = "<xml><ToUserName>ww123</ToUserName><Content>hello</Content></xml>"
        encrypted_b64, sig = self.crypto.encrypt_message(plaintext, "1000", "999")
        recovered = self.crypto.decrypt_message(sig, "1000", "999", encrypted_b64)
        self.assertEqual(recovered, plaintext)

    def test_round_trip_verify_url_style(self):
        # verify_url is just decrypt_message's plumbing, reused for echostr.
        echostr = "some echo content"
        encrypted_b64, sig = self.crypto.encrypt_message(echostr, "1000", "999")
        recovered = self.crypto.verify_url(sig, "1000", "999", encrypted_b64)
        self.assertEqual(recovered, echostr)

    def test_decrypt_rejects_bad_signature(self):
        plaintext = "hello"
        encrypted_b64, _sig = self.crypto.encrypt_message(plaintext, "1000", "999")
        with self.assertRaises(WeComCryptoError):
            self.crypto.decrypt_message("0" * 40, "1000", "999", encrypted_b64)

    def test_decrypt_rejects_wrong_corp_id(self):
        plaintext = "hello"
        other = WeComCrypto(_TEST_TOKEN, _TEST_AES_KEY, "different-corp-id")
        encrypted_b64, sig = other.encrypt_message(plaintext, "1000", "999")
        # Same token/key so signature machinery matches, but corp_id embedded
        # in the payload won't match self.crypto's configured corp_id.
        forged_sig = self.crypto._signature("1000", "999", encrypted_b64)
        with self.assertRaises(WeComCryptoError):
            self.crypto.decrypt_message(forged_sig, "1000", "999", encrypted_b64)

    def test_round_trip_with_unicode_content(self):
        plaintext = "你好，世界！HITL reply: 是"
        encrypted_b64, sig = self.crypto.encrypt_message(plaintext, "42", "7")
        recovered = self.crypto.decrypt_message(sig, "42", "7", encrypted_b64)
        self.assertEqual(recovered, plaintext)

    def test_pkcs7_padding_block_size_is_32(self):
        from app.mcp.adapters.messenger.wecom_crypto import _pkcs7_pad, _pkcs7_unpad

        for length in [0, 1, 16, 31, 32, 33, 63, 64]:
            data = b"x" * length
            padded = _pkcs7_pad(data)
            self.assertEqual(len(padded) % 32, 0)
            self.assertEqual(_pkcs7_unpad(padded), data)


if __name__ == "__main__":
    unittest.main()
