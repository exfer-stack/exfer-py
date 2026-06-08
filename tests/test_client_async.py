"""Async-client mirror of test_client_sync.

We exercise every method shape but skip the wire-detail checks (those
are already exhaustive on the sync side). Focus here: every method
awaits, returns the right unwrapped type, and the env / datadir
constructors close cleanly.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from exfer_walletd import AsyncClient, Tip

WALLETD_URL = "http://walletd.test"
TOKEN = "test-token"
ADDR = "8b0609a812de3b0103dd3b3e78be4a99ef1699b6f02820e1bc1dbcfc75681481"
TX_ID = "a02ab025d75a295540d681f89da3f8bfed894e02cea721085facbf9ad4525c68"
BLOCK_HASH = "17b95f159c3e51440207cc6648f655201bac84fd0e1e5a9ad8461e2d7a2932d5"


def rpc_ok(result: object, *, request_id: int = 1) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "result": result, "id": request_id})


@pytest.fixture
def mock_walletd() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=WALLETD_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def client(mock_walletd: respx.MockRouter) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(WALLETD_URL, TOKEN) as c:
        yield c


pytestmark = pytest.mark.asyncio


async def test_ping_returns_none(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"ok": True}))
    assert await client.ping() is None


async def test_generate_address_returns_str(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"address": ADDR, "pubkey": "de" * 32}))
    out = await client.generate_address()
    assert out == ADDR


async def test_list_addresses(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"addresses": [ADDR]}))
    assert await client.list_addresses() == [ADDR]


async def test_get_balance_returns_int(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"address": ADDR, "balance": 42}))
    assert await client.get_balance(ADDR) == 42


async def test_get_address_utxos(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "address": ADDR,
                "script_hex": None,
                "tip_height": 1,
                "truncated": False,
                "utxos": [],
            }
        )
    )
    out = await client.get_address_utxos(ADDR)
    assert out["utxos"] == []


async def test_get_script_utxos(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "address": None,
                "script_hex": "deadbeef",
                "tip_height": 1,
                "truncated": False,
                "utxos": [],
            }
        )
    )
    out = await client.get_script_utxos("deadbeef")
    assert out["script_hex"] == "deadbeef"


async def test_get_block_height_returns_int(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"height": 1, "block_id": BLOCK_HASH}))
    assert await client.get_block_height() == 1


async def test_get_tip_returns_named_tuple(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"height": 7, "block_id": BLOCK_HASH}))
    tip = await client.get_tip()
    assert isinstance(tip, Tip)
    assert (tip.height, tip.block_id) == (7, BLOCK_HASH)


def _block_result() -> dict[str, Any]:
    return {
        "hash": BLOCK_HASH,
        "height": 1,
        "prev_block_id": "00" * 32,
        "state_root": "11" * 32,
        "tx_root": "22" * 32,
        "timestamp": 0,
        "nonce": 0,
        "difficulty_target": "ff" * 32,
        "tx_count": 0,
        "transactions": [],
    }


async def test_get_block_by_height(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok(_block_result()))
    await client.get_block_by_height(1)
    body = json.loads(route.calls.last.request.content)
    assert body["params"] == {"height": 1}


async def test_get_block_by_hash(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok(_block_result()))
    await client.get_block_by_hash(BLOCK_HASH)
    body = json.loads(route.calls.last.request.content)
    assert body["params"] == {"hash": BLOCK_HASH}


async def test_get_transaction(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "tx_id": TX_ID,
                "tx_hex": "01000200deadbeef",
                "in_mempool": True,
                "block_hash": None,
                "block_height": None,
            }
        )
    )
    out = await client.get_transaction(TX_ID)
    assert out["in_mempool"] is True
    body = json.loads(route.calls.last.request.content)
    assert body["params"] == {"hash": TX_ID}


async def test_transfer_wire_field_is_from(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    route = mock_walletd.post("/").mock(
        return_value=rpc_ok({"tx_id": TX_ID, "size": 1, "tip_height": 1, "submitted": True})
    )
    await client.transfer(from_=ADDR, to="ee" * 32, amount=10)
    body = json.loads(route.calls.last.request.content)
    assert body["params"] == {"from": ADDR, "to": "ee" * 32, "amount": 10}


async def test_send_raw_transaction_returns_str(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"tx_id": TX_ID}))
    out = await client.send_raw_transaction("01000200")
    assert isinstance(out, str)
    assert out == TX_ID


# ---------------------------------------------------------------------------
# EXFER-QUOTE (quote_issue / quote_verify)
# ---------------------------------------------------------------------------

PAYEE_PUBKEY = "de" * 32
SIGNER_PUBKEY = "ab" * 32
SIGNATURE = "ff" * 64
GENESIS = "00" * 32
QUOTE_ID = "abababababababababababababababab"

QUOTE_JSON = {
    "version": 1,
    "quote_id": QUOTE_ID,
    "currency": "USD",
    "amount_minor": 1250,
    "rate_exfers_per_unit": 4000000000,
    "exfer_amount": 50000000000,
    "payee_pubkey": PAYEE_PUBKEY,
    "issued_at": 1781000000,
    "expires_at": 1781000300,
    "memo": "roundtrip",
    "signer_pubkey": SIGNER_PUBKEY,
    "signature": SIGNATURE,
}


def _quote_issue_result() -> dict[str, Any]:
    return {
        "quote": QUOTE_JSON,
        "signature": SIGNATURE,
        "signer_address": ADDR,
        "payee_address": "ee" * 32,
        "genesis_block_id": GENESIS,
        "image": "deadbeef",
        "htlc_preimage": "11" * 32,
        "htlc_hash_lock": "22" * 32,
    }


async def test_quote_issue_wire_request_and_unpack(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok(_quote_issue_result()))
    out = await client.quote_issue(
        address=ADDR,
        payee_pubkey=PAYEE_PUBKEY,
        currency="USD",
        amount_minor=1250,
        rate_exfers_per_unit=4000000000,
        exfer_amount=50000000000,
        ttl_secs=300,
        memo="note",
        quote_id=QUOTE_ID,
    )
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "quote_issue"
    assert body["params"] == {
        "address": ADDR,
        "payee_pubkey": PAYEE_PUBKEY,
        "currency": "USD",
        "amount_minor": 1250,
        "rate_exfers_per_unit": 4000000000,
        "exfer_amount": 50000000000,
        "ttl_secs": 300,
        "memo": "note",
        "quote_id": QUOTE_ID,
    }
    assert out["signer_address"] == ADDR
    assert out["htlc_hash_lock"] == "22" * 32


async def test_quote_verify_wire_request_and_unpack(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    route = mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "valid": True,
                "signer_address": ADDR,
                "payee_address": "ee" * 32,
                "genesis_block_id": GENESIS,
            }
        )
    )
    out = await client.quote_verify(QUOTE_JSON)
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "quote_verify"
    assert body["params"] == {"quote": QUOTE_JSON}
    assert out["valid"] is True
    assert out["genesis_block_id"] == GENESIS


# ---------------------------------------------------------------------------
# Errors propagate
# ---------------------------------------------------------------------------


async def test_authentication_error_propagates(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    from exfer_walletd import AuthenticationError

    mock_walletd.post("/").mock(
        return_value=httpx.Response(
            401,
            json={
                "jsonrpc": "2.0",
                "error": {"code": -32001, "message": "authentication required"},
                "id": 1,
            },
        )
    )
    with pytest.raises(AuthenticationError):
        await client.ping()


async def test_transport_error_propagates(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    from exfer_walletd import TransportError

    mock_walletd.post("/").mock(side_effect=httpx.ConnectError("nope"))
    with pytest.raises(TransportError):
        await client.ping()


# ---------------------------------------------------------------------------
# Healthz + lifecycle
# ---------------------------------------------------------------------------


async def test_healthz_ok(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.get("/healthz").mock(return_value=httpx.Response(200, text="ok\n"))
    assert await client.healthz() is True


async def test_healthz_transport_failure(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.get("/healthz").mock(side_effect=httpx.ConnectError("down"))
    assert await client.healthz() is False


async def test_context_manager_closes_http() -> None:
    async with AsyncClient(WALLETD_URL, TOKEN) as c:
        http = c._http
        assert not http.is_closed
    assert http.is_closed


# ---------------------------------------------------------------------------
# Alternate constructors
# ---------------------------------------------------------------------------


async def test_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WALLETD_URL", WALLETD_URL)
    monkeypatch.setenv("WALLETD_AUTH_TOKEN", "env-token")
    c = AsyncClient.from_env()
    try:
        assert c._token == "env-token"
    finally:
        await c.aclose()


async def test_from_datadir(tmp_path: Path) -> None:
    (tmp_path / "token").write_text("file-tok")
    c = AsyncClient.from_datadir(url="http://x", datadir=str(tmp_path))
    try:
        assert c._token == "file-tok"
    finally:
        await c.aclose()
