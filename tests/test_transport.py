"""Wire-level checks: envelope shape, headers, decoding edge cases."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from exfer_walletd import Client, ProtocolError, TransportError
from exfer_walletd._transport import build_envelope, decode_response

from .conftest import TOKEN, WALLETD_URL, rpc_ok


def test_build_envelope_shape() -> None:
    env = build_envelope("ping", None, 7)
    assert env == {"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 7}


def test_build_envelope_copies_params() -> None:
    p = {"address": "abc"}
    env = build_envelope("get_balance", p, 1)
    assert env["params"] == p
    # mutating the original must not bleed into the envelope
    p["address"] = "mutated"
    assert env["params"] == {"address": "abc"}


def test_authorization_header_sent(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok({"ok": True}))
    client.ping()
    assert route.calls.last is not None
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert req.headers["content-type"].startswith("application/json")


def test_ids_increment_per_call(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok({"ok": True}))
    client.ping()
    client.ping()
    client.ping()
    ids = [json.loads(call.request.content)["id"] for call in route.calls]
    assert ids == [1, 2, 3]


def test_jsonrpc_envelope_method_and_params(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok({"address": "ff" * 32, "balance": 0}))
    client.get_balance("ff" * 32)
    body = json.loads(route.calls.last.request.content)
    assert body["jsonrpc"] == "2.0"
    assert body["method"] == "get_balance"
    assert body["params"] == {"address": "ff" * 32}


def test_healthz_uses_get_no_auth(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.get("/healthz").mock(return_value=httpx.Response(200, text="ok\n"))
    assert client.healthz() is True
    assert "authorization" not in route.calls.last.request.headers


def test_healthz_returns_false_on_non_ok_body(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.get("/healthz").mock(return_value=httpx.Response(200, text="DEGRADED"))
    assert client.healthz() is False


def test_healthz_returns_false_on_transport_error(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.get("/healthz").mock(side_effect=httpx.ConnectError("nope"))
    assert client.healthz() is False


def test_transport_error_on_unreachable(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(TransportError) as exc:
        client.ping()
    assert "walletd unreachable" in str(exc.value)


def test_transport_error_on_non_json_body() -> None:
    resp = httpx.Response(200, text="<html>not json</html>")
    with pytest.raises(TransportError) as exc:
        decode_response(resp)
    assert "non-JSON" in str(exc.value)


def test_protocol_error_on_missing_result_and_error() -> None:
    resp = httpx.Response(200, json={"jsonrpc": "2.0", "id": 1})
    with pytest.raises(ProtocolError):
        decode_response(resp)


def test_protocol_error_on_non_object_body() -> None:
    resp = httpx.Response(200, json=["not", "a", "dict"])
    with pytest.raises(ProtocolError):
        decode_response(resp)


def test_unexpected_http_status_is_transport_error() -> None:
    resp = httpx.Response(503, text="bad gateway")
    with pytest.raises(TransportError) as exc:
        decode_response(resp)
    assert "HTTP 503" in str(exc.value)


def test_url_trailing_slash_is_stripped() -> None:
    # Make sure http://x:8080/ doesn't become http://x:8080//
    c = Client("http://x.test/", "tok")
    assert c._url == "http://x.test"


def test_empty_token_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        Client("http://x", "")


def test_context_manager_closes_http(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []

    real_close = httpx.Client.close

    def spy_close(self: httpx.Client) -> Any:
        closed.append(True)
        return real_close(self)

    monkeypatch.setattr(httpx.Client, "close", spy_close)
    with Client(WALLETD_URL, TOKEN):
        pass
    assert closed == [True]
