"""HTTP transport and JSON-RPC envelope handling.

This module is *internal* — the public surface is :class:`Client` and
:class:`AsyncClient`. We split the envelope build / response decode here
so the sync and async clients share exactly the same wire logic and
neither can drift from the other.

The fingerprint-pinning transports (:class:`_FingerprintHTTPTransport`,
:class:`_FingerprintAsyncHTTPTransport`) wrap httpx's default transports
and verify that the TLS leaf cert SHA-256 matches what the caller pinned
— this is how the SDK trusts walletd's self-signed cert without involving
the CA chain at all.

There are intentionally no retries here. ``exfer-walletd`` already retries
its own upstream node calls with linear backoff (see ``RetryPolicy`` in
``exfer-walletd/src/upstream/mod.rs``); stacking another retry on every
HTTP call would multiply latency for no benefit. Callers can wrap a single
method in their own retry loop if walletd itself is flaky.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import re
from collections.abc import Mapping
from typing import Any

import httpx

from .errors import (
    AuthenticationError,
    FingerprintMismatchError,
    ParseError,
    ProtocolError,
    TransportError,
    error_for_code,
)

JsonObject = dict[str, Any]


def build_envelope(method: str, params: Mapping[str, Any] | None, request_id: int) -> JsonObject:
    """Construct a JSON-RPC 2.0 request envelope.

    Walletd treats missing ``params`` as ``{}``, but we always send an
    object so wire dumps are unambiguous.
    """
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": dict(params) if params is not None else {},
        "id": request_id,
    }


def decode_response(resp: httpx.Response) -> Any:
    """Decode a walletd JSON-RPC response and raise on error.

    HTTP framing rules (matching ``exfer-walletd/src/error.rs::http_status``):

    - HTTP 401: always an auth failure, body may or may not be valid JSON.
    - HTTP 400: parse error from walletd's envelope decoder.
    - HTTP 200: either a success or a JSON-RPC application error.

    Anything else (5xx, 3xx redirects, etc.) is a :class:`TransportError`
    because it indicates walletd itself is misbehaving or a proxy
    intervened — not a normal RPC outcome.
    """
    status = resp.status_code

    # Auth failures: walletd returns 401 + a JSON body. If a proxy strips
    # the body or returns plaintext, still raise AuthenticationError so
    # callers don't see a confusing TransportError on a clear-cut 401.
    if status == 401:
        message = _safe_message(resp, default="authentication required")
        raise AuthenticationError(message, code=-32001)

    # Parse errors: walletd returns 400 + a JSON-RPC error body.
    if status == 400:
        body = _parse_json_or_raise(resp)
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            raise error_for_code(
                int(err.get("code", -32700)),
                str(err.get("message", "parse error")),
                err.get("data"),
            )
        raise ParseError("parse error", code=-32700)

    # Anything other than 200 at this point is transport-layer noise.
    if status != 200:
        raise TransportError(f"unexpected HTTP {status} from walletd: {resp.text[:200]!r}")

    body = _parse_json_or_raise(resp)
    if not isinstance(body, dict):
        raise ProtocolError(f"walletd returned non-object body: {body!r}")

    if "error" in body and body["error"] is not None:
        err = body["error"]
        if not isinstance(err, dict):
            raise ProtocolError(f"walletd error envelope is not an object: {err!r}")
        raise error_for_code(
            int(err.get("code", 0)),
            str(err.get("message", "")),
            err.get("data"),
        )

    if "result" not in body:
        raise ProtocolError(f"walletd response missing both result and error: {body!r}")

    return body["result"]


def _parse_json_or_raise(resp: httpx.Response) -> Any:
    """Parse the response body as JSON or raise :class:`TransportError`.

    walletd always emits JSON for the JSON-RPC endpoint; a non-JSON body
    here means something between us and walletd has rewritten the response.
    """
    try:
        return resp.json()
    except ValueError as exc:
        raise TransportError(
            f"walletd returned non-JSON body (HTTP {resp.status_code}): {resp.text[:200]!r}"
        ) from exc


def _safe_message(resp: httpx.Response, *, default: str) -> str:
    """Best-effort extraction of the JSON-RPC ``error.message`` from a 401.

    Falls back to ``default`` if the body is missing, non-JSON, or has the
    wrong shape — callers still get a useful exception either way.
    """
    try:
        body = resp.json()
    except ValueError:
        return default
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            msg = err.get("message")
            if isinstance(msg, str) and msg:
                return msg
    return default


class _IdCounter:
    """Monotonic JSON-RPC request id generator.

    Walletd doesn't care about the id beyond echoing it; we still emit a
    counter so wire dumps and per-call logs can be correlated.
    """

    def __init__(self) -> None:
        self._it = itertools.count(1)

    def next(self) -> int:
        return next(self._it)


def wrap_httpx_error(exc: httpx.HTTPError) -> TransportError:
    """Convert an httpx connection / timeout error to :class:`TransportError`."""
    return TransportError(f"walletd unreachable: {exc}")


__all__ = [
    "JsonObject",
    "_FingerprintAsyncHTTPTransport",
    "_FingerprintHTTPTransport",
    "_IdCounter",
    "build_envelope",
    "decode_response",
    "parse_fingerprint",
    "wrap_httpx_error",
]


# ---------------------------------------------------------------------------
# Fingerprint pinning
# ---------------------------------------------------------------------------


_FINGERPRINT_RE = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


def parse_fingerprint(s: str) -> bytes:
    """Validate and decode a `sha256:<hex>` fingerprint string.

    The `sha256:` prefix is mandatory so we have room to add other hash
    algorithms later without breaking existing config. Bare hex is
    rejected with a clear error.
    """
    if not isinstance(s, str):
        raise ValueError(f"fingerprint must be a string, got {type(s).__name__}")
    m = _FINGERPRINT_RE.match(s.strip())
    if not m:
        raise ValueError(
            f"invalid fingerprint {s!r}: expected 'sha256:<64-hex-char>' "
            f"(walletd writes this in <datadir>/cert.fingerprint)"
        )
    return bytes.fromhex(m.group(1).lower())


def _format_fingerprint(digest: bytes) -> str:
    return f"sha256:{digest.hex()}"


def _verify_peer_fingerprint(response: httpx.Response, expected: bytes) -> None:
    """Extract the TLS peer cert from a response and compare its SHA-256.

    Raises :class:`FingerprintMismatchError` on mismatch,
    :class:`TransportError` if we couldn't reach a TLS stream at all
    (e.g. the response came back over plain HTTP, meaning either walletd
    isn't configured for TLS or something downgraded the connection).
    """
    stream = response.extensions.get("network_stream")
    if stream is None:
        raise TransportError(
            "fingerprint pinning is configured but the response carried no "
            "network stream; HTTPS is required when fingerprint= is set"
        )
    ssl_object = stream.get_extra_info("ssl_object")
    if ssl_object is None:
        raise TransportError(
            "fingerprint pinning is configured but the connection isn't TLS; use an https:// URL"
        )
    # binary_form is positional-only on stdlib ssl._SSLSocket — passing
    # it as kwarg blows up at runtime with TypeError.
    peer_der = ssl_object.getpeercert(True)
    if not peer_der:
        raise TransportError("TLS peer presented no certificate")
    actual = hashlib.sha256(peer_der).digest()
    if not hmac.compare_digest(actual, expected):
        raise FingerprintMismatchError(
            expected=_format_fingerprint(expected),
            actual=_format_fingerprint(actual),
        )


class _FingerprintHTTPTransport(httpx.HTTPTransport):
    """Sync transport that pins the TLS leaf cert SHA-256.

    `verify=False` tells httpx to skip CA-chain validation — we trust the
    cert by hash, not by issuer. Hostname verification is also skipped:
    a self-signed leaf that hashes to the pinned value is by definition
    the right peer.
    """

    def __init__(self, expected_sha256: bytes, **kw: Any) -> None:
        super().__init__(verify=False, **kw)
        self._expected = expected_sha256

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = super().handle_request(request)
        _verify_peer_fingerprint(response, self._expected)
        return response


class _FingerprintAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """Async mirror of :class:`_FingerprintHTTPTransport`."""

    def __init__(self, expected_sha256: bytes, **kw: Any) -> None:
        super().__init__(verify=False, **kw)
        self._expected = expected_sha256

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)
        _verify_peer_fingerprint(response, self._expected)
        return response
