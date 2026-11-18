"""AES-256-GCM at the application layer (DESIGN §5 🔒 fields, §8.5 per-session keys).

Ciphertext layout: 1-byte version | 12-byte nonce | GCM ciphertext+tag. The associated data binds a value to its
row or Redis key, so a ciphertext copied elsewhere fails to decrypt.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from selector.config import Settings

VERSION = b"\x01"
KEY_BYTES = 32


class CryptoError(ValueError):
    pass


def new_key() -> bytes:
    return os.urandom(KEY_BYTES)


def encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    if len(key) != KEY_BYTES:
        raise CryptoError("key must be 32 bytes")
    nonce = os.urandom(12)
    return VERSION + nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def decrypt(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(key) != KEY_BYTES or len(blob) < 1 + 12 + 16 or blob[:1] != VERSION:
        raise CryptoError("bad ciphertext")
    try:
        return AESGCM(key).decrypt(blob[1:13], blob[13:], aad)
    except InvalidTag as e:
        raise CryptoError("decryption failed") from e


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (binascii.Error, ValueError) as e:
        raise CryptoError("bad base64") from e


def profile_key(settings: Settings) -> bytes | None:
    """The server key for Saved mode (`PROFILE_ENC_KEY`, base64 32 bytes), or None if not configured."""
    raw = settings.profile_enc_key.get_secret_value().strip()
    if not raw:
        return None
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as e:
        raise CryptoError("PROFILE_ENC_KEY is not valid base64") from e
    if len(key) != KEY_BYTES:
        raise CryptoError("PROFILE_ENC_KEY must decode to 32 bytes")
    return key
