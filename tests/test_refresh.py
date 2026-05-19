"""refresh_address + refresh_addresses — sync and async.

v0.14.0 walletd defaults to manual cache refresh; apps drive cadence
via these methods. respx mocks the wire layer.
"""

from __future__ import annotations

import pytest
import respx

from exfer_walletd import AsyncClient, Client

from .conftest import TOKEN, WALLETD_URL, rpc_ok

SAMPLE_ROW = {
    "address": "ab" * 32,
    "balance": 7_777_777,
    "utxo_count": 3,
    "fetched_at_ms_ago": 12,
    "tip_at_fetch": 589912,
    "stale": False,
    "last_error": None,
}

SAMPLE_BATCH_ENVELOPE = {
    "tip": {"height": 589912, "block_id": "ab" * 32},
    "as_of_ms_ago": 5,
    "addresses": [
        {
            "address": "11" * 32,
            "balance": 100,
            "utxo_count": 1,
            "fetched_at_ms_ago": 10,
            "tip_at_fetch": 589912,
            "stale": False,
            "last_error": None,
        },
        {
            "address": "22" * 32,
            "balance": 200,
            "utxo_count": 2,
            "fetched_at_ms_ago": 8,
            "tip_at_fetch": 589912,
            "stale": False,
            "last_error": None,
        },
    ],
}


def test_refresh_address_returns_post_refresh_row(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok({"address": SAMPLE_ROW}))

    row = client.refresh_address("ab" * 32)

    assert route.called
    assert row["address"] == "ab" * 32
    assert row["balance"] == 7_777_777
    assert row["utxo_count"] == 3
    assert row["stale"] is False
    assert row["last_error"] is None


def test_refresh_address_surfaces_last_error_for_rate_limited_call(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    error_row = {
        **SAMPLE_ROW,
        "balance": None,
        "utxo_count": None,
        "stale": True,
        "last_error": "Rate limit exceeded: max 30/min",
    }
    mock_walletd.post("/").mock(return_value=rpc_ok({"address": error_row}))

    row = client.refresh_address("ab" * 32)

    assert row["balance"] is None
    assert row["stale"] is True
    assert row["last_error"] is not None
    assert "Rate limit" in row["last_error"]


def test_refresh_address_raises_on_bad_shape(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"oops": "no address key"}))
    with pytest.raises(RuntimeError, match="refresh_address returned unexpected shape"):
        client.refresh_address("ab" * 32)


def test_refresh_addresses_returns_full_envelope(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok(SAMPLE_BATCH_ENVELOPE))

    result = client.refresh_addresses(["11" * 32, "22" * 32])

    assert result["tip"]["height"] == 589912
    assert len(result["addresses"]) == 2
    assert result["addresses"][0]["balance"] == 100
    assert result["addresses"][1]["balance"] == 200


@pytest.mark.asyncio
async def test_refresh_address_async(mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"address": SAMPLE_ROW}))
    async with AsyncClient(WALLETD_URL, TOKEN) as c:
        row = await c.refresh_address("ab" * 32)
    assert row["balance"] == 7_777_777


@pytest.mark.asyncio
async def test_refresh_addresses_async(mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok(SAMPLE_BATCH_ENVELOPE))
    async with AsyncClient(WALLETD_URL, TOKEN) as c:
        result = await c.refresh_addresses(["11" * 32, "22" * 32])
    assert len(result["addresses"]) == 2
