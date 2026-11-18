"""AES-GCM helpers, the PROFILE_ENC_KEY parser and the msp_sid cookie format."""

from __future__ import annotations

import base64

import pytest

from selector import crypto
from selector.api import cookies
from selector.config import Settings


def test_roundtrip_and_aad_binding() -> None:
    k = crypto.new_key()
    blob = crypto.encrypt(k, b"zzfakedrug", b"eph:abc:profile")
    assert b"zzfakedrug" not in blob
    assert crypto.decrypt(k, blob, b"eph:abc:profile") == b"zzfakedrug"
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(k, blob, b"eph:other:profile")  # copied to another key → fails
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(crypto.new_key(), blob, b"eph:abc:profile")  # without the cookie key → fails (N8)
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(k, blob[:-1] + bytes([blob[-1] ^ 1]), b"eph:abc:profile")


def test_nonce_is_random() -> None:
    k = crypto.new_key()
    assert crypto.encrypt(k, b"x", b"a") != crypto.encrypt(k, b"x", b"a")


def test_profile_key() -> None:
    assert crypto.profile_key(Settings(_env_file=None)) is None
    raw = base64.b64encode(bytes(range(32))).decode()
    assert crypto.profile_key(Settings(_env_file=None, profile_enc_key=raw)) == bytes(range(32))
    with pytest.raises(crypto.CryptoError):
        crypto.profile_key(Settings(_env_file=None, profile_enc_key=base64.b64encode(b"short").decode()))


@pytest.mark.parametrize("mode", ["nosave", "saved"])
def test_cookie_roundtrip(mode: str) -> None:
    h = cookies.new_handle(mode)
    v = cookies.encode(h)
    assert v.startswith(f"v1.{mode[0]}.")
    back = cookies.decode(v)
    assert back is not None and back.sid == h.sid and back.mode == mode and back.key == h.key
    assert (h.key is not None) == (mode == "nosave")


@pytest.mark.parametrize(
    "bad",
    ["", "v2.n.x.y", "v1.x.abc", "v1.n." + "A" * 43, "v1.s." + "A" * 43 + "." + "A" * 43, "v1.n.!!!.###", "x" * 300],
)
def test_cookie_rejects_garbage(bad: str) -> None:
    assert cookies.decode(bad) is None
