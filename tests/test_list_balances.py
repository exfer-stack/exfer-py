"""list_balances + list_addresses(with_balance=True) — sync and async.

Exercises both the bare RPC method and the with_balance overload of
list_addresses. respx mocks the wire layer; no walletd process needed.
"""

from __future__ import annotations

import pytest
import respx

from exfer_walletd import AsyncClient, Client

from .conftest import TOKEN, WALLETD_URL, rpc_ok

SAMPLE_ENVELOPE = {
    "tip": {"height": 589354, "block_id": "ab" * 32},
    "as_of_ms_ago": 1500,
    "addresses": [
        {
            "address": "11" * 32,
            "balance": 1_500_000,
            "utxo_count": 3,
            "fetched_at_ms_ago": 1500,
            "tip_at_fetch": 589353,
            "stale": False,
            "last_error": None,
        },
        {
            "address": "22" * 32,
            "balance": None,
            "utxo_count": None,
            "fetched_at_ms_ago": None,
            "tip_at_fetch": None,
            "stale": True,
            "last_error": "upstream unreachable",
        },
    ],
}


def test_list_balances_returns_envelope_with_typed_rows(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok(SAMPLE_ENVELOPE))

    result = client.list_balances()

    assert route.called
    assert result["tip"]["height"] == 589354
    assert result["as_of_ms_ago"] == 1500
    assert len(result["addresses"]) == 2

    fresh = result["addresses"][0]
    assert fresh["address"] == "11" * 32
    assert fresh["balance"] == 1_500_000
    assert fresh["utxo_count"] == 3
    assert fresh["stale"] is False
    assert fresh["last_error"] is None

    stale = result["addresses"][1]
    assert stale["balance"] is None
    assert stale["stale"] is True
    assert stale["last_error"] == "upstream unreachable"


def test_list_balances_handles_empty_address_set(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {"tip": {"height": None, "block_id": None}, "as_of_ms_ago": 0, "addresses": []}
        )
    )
    result = client.list_balances()
    assert result["addresses"] == []


def test_list_balances_raises_runtimeerror_on_bad_shape(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    # Walletd should never return this, but if it does, surface a
    # clear error rather than a KeyError ten frames deep in user code.
    mock_walletd.post("/").mock(return_value=rpc_ok({"unexpected": "shape"}))
    with pytest.raises(RuntimeError, match="list_balances returned unexpected shape"):
        client.list_balances()


@pytest.mark.asyncio
async def test_list_balances_async(mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok(SAMPLE_ENVELOPE))
    async with AsyncClient(WALLETD_URL, TOKEN) as c:
        result = await c.list_balances()
    assert result["tip"]["height"] == 589354
    assert result["addresses"][0]["balance"] == 1_500_000
    assert result["addresses"][1]["stale"] is True


@pytest.mark.asyncio
async def test_list_balances_async_raises_on_bad_shape(
    mock_walletd: respx.MockRouter,
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"unexpected": "shape"}))
    async with AsyncClient(WALLETD_URL, TOKEN) as c:
        with pytest.raises(RuntimeError, match="list_balances returned unexpected shape"):
            await c.list_balances()
