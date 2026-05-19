"""HTTP transport and JSON-RPC envelope handling.

This module is *internal* — the public surface is :class:`Client` and
:class:`AsyncClient`. We split the envelope build / response decode here
so the sync and async clients share exactly the same wire logic and
neither can drift from the other.

There are intentionally no retries here. ``exfer-walletd`` already retries
its own upstream node calls with linear backoff (see ``RetryPolicy`` in
``exfer-walletd/src/upstream/mod.rs``); stacking another retry on every
HTTP call would multiply latency for no benefit. Callers can wrap a single
method in their own retry loop if walletd itself is flaky.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from typing import Any

import httpx

from .errors import (
    AuthenticationError,
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
    "_IdCounter",
    "build_envelope",
    "decode_response",
    "wrap_httpx_error",
]
