"""Fingerprint parsing, wiring into Client/AsyncClient, and the mismatch path.

End-to-end fingerprint verification against a real walletd lives in
the integration suite (`tests/integration/test_roundtrip.py`); here we
cover the SDK-side surface in isolation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from exfer import AsyncClient, Client, FingerprintMismatchError
from exfer._transport import (
    _FingerprintAsyncHTTPTransport,
    _FingerprintHTTPTransport,
    _verify_peer_fingerprint,
    parse_fingerprint,
)

TOKEN = "test-token"
GOOD_FP_HEX = "b66953c47263ac0da8192676e4770f0f799563322985c57246a6fab1bf24aa86"
GOOD_FP = f"sha256:{GOOD_FP_HEX}"


# ---------------------------------------------------------------------------
# parse_fingerprint
# ---------------------------------------------------------------------------


def test_parse_fingerprint_canonical() -> None:
    out = parse_fingerprint(GOOD_FP)
    assert out == bytes.fromhex(GOOD_FP_HEX)


def test_parse_fingerprint_uppercase_hex_normalises() -> None:
    out = parse_fingerprint(f"sha256:{GOOD_FP_HEX.upper()}")
    assert out == bytes.fromhex(GOOD_FP_HEX)


def test_parse_fingerprint_strips_whitespace() -> None:
    assert parse_fingerprint(f"  {GOOD_FP}\n") == bytes.fromhex(GOOD_FP_HEX)


@pytest.mark.parametrize(
    "bad",
    [
        GOOD_FP_HEX,  # bare hex — must require sha256: prefix
        "sha1:" + ("ab" * 20),  # unsupported algorithm
        "sha256:" + ("ab" * 31),  # too short
        "sha256:" + ("ab" * 33),  # too long
        "sha256:NotHex" + ("0" * 58),  # non-hex chars
        "",
    ],
)
def test_parse_fingerprint_rejects_bad_input(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_fingerprint(bad)


# ---------------------------------------------------------------------------
# Client wiring
# ---------------------------------------------------------------------------


def test_client_with_https_and_fingerprint_installs_pinning_transport() -> None:
    c = Client("https://walletd.example:7448", TOKEN, fingerprint=GOOD_FP)
    try:
        # The httpx.Client builds a wrapper around our transport; the
        # underlying transport on the default pool is what we passed in.
        assert isinstance(c._http._transport, _FingerprintHTTPTransport)
        assert c._http._transport._expected == bytes.fromhex(GOOD_FP_HEX)
    finally:
        c.close()


def test_client_http_with_fingerprint_raises() -> None:
    with pytest.raises(ValueError, match="requires an https:// URL"):
        Client("http://walletd.example:7448", TOKEN, fingerprint=GOOD_FP)


def test_client_rejects_both_transport_and_fingerprint() -> None:
    custom = httpx.HTTPTransport()
    try:
        with pytest.raises(ValueError, match="not both"):
            Client("https://x", TOKEN, transport=custom, fingerprint=GOOD_FP)
    finally:
        custom.close()


def test_async_client_with_https_and_fingerprint_installs_pinning_transport() -> None:
    c = AsyncClient("https://walletd.example:7448", TOKEN, fingerprint=GOOD_FP)
    try:
        assert isinstance(c._http._transport, _FingerprintAsyncHTTPTransport)
    finally:
        # Synchronous teardown is fine when no requests have flown.
        pass


def test_async_client_http_with_fingerprint_raises() -> None:
    with pytest.raises(ValueError, match="requires an https:// URL"):
        AsyncClient("http://x", TOKEN, fingerprint=GOOD_FP)


# ---------------------------------------------------------------------------
# Mismatch via injected fake response
# ---------------------------------------------------------------------------


class _FakeSSLObject:
    def __init__(self, der: bytes) -> None:
        self._der = der

    def getpeercert(self, binary_form: bool = False, /) -> bytes:
        # binary_form is positional-only — match the stdlib signature.
        assert binary_form, "exfer-py only ever asks for binary_form=True"
        return self._der


class _FakeStream:
    def __init__(self, ssl_object: _FakeSSLObject | None) -> None:
        self._ssl = ssl_object

    def get_extra_info(self, key: str) -> _FakeSSLObject | None:
        return self._ssl if key == "ssl_object" else None


def _fake_response(ssl_object: _FakeSSLObject | None) -> httpx.Response:
    resp = httpx.Response(200, json={"ok": True})
    resp.extensions["network_stream"] = _FakeStream(ssl_object)
    return resp


def test_verify_peer_fingerprint_matches() -> None:
    fake_cert = b"\x30\x82" + b"\x00" * 100  # bytes don't have to be a real cert
    expected = hashlib.sha256(fake_cert).digest()
    resp = _fake_response(_FakeSSLObject(fake_cert))
    _verify_peer_fingerprint(resp, expected)  # must not raise


def test_verify_peer_fingerprint_mismatch_raises() -> None:
    expected = hashlib.sha256(b"the-pinned-cert").digest()
    resp = _fake_response(_FakeSSLObject(b"some-OTHER-cert"))
    with pytest.raises(FingerprintMismatchError) as excinfo:
        _verify_peer_fingerprint(resp, expected)
    assert excinfo.value.expected.startswith("sha256:")
    assert excinfo.value.actual.startswith("sha256:")
    assert excinfo.value.expected != excinfo.value.actual


def test_verify_peer_fingerprint_no_ssl_means_transport_error() -> None:
    from exfer import TransportError

    resp = _fake_response(None)
    with pytest.raises(TransportError, match="isn't TLS"):
        _verify_peer_fingerprint(resp, b"\x00" * 32)


def test_verify_peer_fingerprint_no_network_stream_means_transport_error() -> None:
    from exfer import TransportError

    resp = httpx.Response(200, json={"ok": True})  # no network_stream extension
    with pytest.raises(TransportError, match="no network stream"):
        _verify_peer_fingerprint(resp, b"\x00" * 32)


def test_fingerprint_mismatch_is_a_transport_error_too() -> None:
    from exfer import ExferError, TransportError

    # Catching either of these must catch FingerprintMismatchError.
    assert issubclass(FingerprintMismatchError, TransportError)
    assert issubclass(FingerprintMismatchError, ExferError)


# ---------------------------------------------------------------------------
# Constructor convenience: from_env / from_datadir
# ---------------------------------------------------------------------------


def test_from_env_reads_fingerprint_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WALLETD_URL", "https://walletd.example:7448")
    monkeypatch.setenv("WALLETD_AUTH_TOKEN", "env-token")
    monkeypatch.setenv("WALLETD_FINGERPRINT", GOOD_FP)
    c = Client.from_env()
    try:
        assert isinstance(c._http._transport, _FingerprintHTTPTransport)
    finally:
        c.close()


def test_from_env_skips_fingerprint_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WALLETD_URL", "http://walletd.example:7448")
    monkeypatch.setenv("WALLETD_AUTH_TOKEN", "env-token")
    monkeypatch.delenv("WALLETD_FINGERPRINT", raising=False)
    c = Client.from_env()
    try:
        assert not isinstance(c._http._transport, _FingerprintHTTPTransport)
    finally:
        c.close()


def test_from_datadir_reads_cert_fingerprint_when_https(tmp_path: Path) -> None:
    (tmp_path / "token").write_text("tok\n")
    (tmp_path / "cert.fingerprint").write_text(f"{GOOD_FP}\n")
    c = Client.from_datadir(url="https://localhost:7448", datadir=str(tmp_path))
    try:
        assert isinstance(c._http._transport, _FingerprintHTTPTransport)
    finally:
        c.close()


def test_from_datadir_skips_fingerprint_when_http(tmp_path: Path) -> None:
    (tmp_path / "token").write_text("tok\n")
    # cert.fingerprint may or may not exist; either way http must NOT read it.
    (tmp_path / "cert.fingerprint").write_text(f"{GOOD_FP}\n")
    c = Client.from_datadir(url="http://localhost:7448", datadir=str(tmp_path))
    try:
        assert not isinstance(c._http._transport, _FingerprintHTTPTransport)
    finally:
        c.close()


def test_from_datadir_https_without_fingerprint_file_raises(tmp_path: Path) -> None:
    (tmp_path / "token").write_text("tok\n")
    with pytest.raises(FileNotFoundError, match="fingerprint file not found"):
        Client.from_datadir(url="https://localhost:7448", datadir=str(tmp_path))
