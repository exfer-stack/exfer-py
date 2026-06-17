"""Async-client mirror of :mod:`tests.test_v1_9_sync`.

We exercise every new method shape but skip the body / wire-detail
assertions (those are already exhaustive on the sync side). Focus here:
every method awaits, returns the right unwrapped type, error mapping
fires.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import respx

from exfer import AsyncClient, IndexerNotConfiguredError, WaitTimeoutError

WALLETD_URL = "http://walletd.test"
TOKEN = "test-token"
ADDR = "8b0609a812de3b0103dd3b3e78be4a99ef1699b6f02820e1bc1dbcfc75681481"
ADDR2 = "11" * 32
TX_ID = "a02ab025d75a295540d681f89da3f8bfed894e02cea721085facbf9ad4525c68"
LOCK_TX_ID = "cc" * 32
HASH_LOCK = "33" * 32
BLOCK_HASH = "17b95f159c3e51440207cc6648f655201bac84fd0e1e5a9ad8461e2d7a2932d5"
PUBKEY_RECEIVER = "22" * 32
PUBKEY_SENDER = "11" * 32


def rpc_ok(result: object, *, request_id: int = 1) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "result": result, "id": request_id})


def rpc_err(code: int, message: str, *, request_id: int = 1) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "error": {"code": code, "message": message},
            "id": request_id,
        },
    )


@pytest.fixture
def mock_walletd() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=WALLETD_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def client(mock_walletd: respx.MockRouter) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(WALLETD_URL, TOKEN) as c:
        yield c


pytestmark = pytest.mark.asyncio


def _htlc_record_fixture() -> dict[str, object]:
    return {
        "lock_tx_id": LOCK_TX_ID,
        "output_index": 0,
        "params": {
            "sender": PUBKEY_SENDER,
            "receiver": PUBKEY_RECEIVER,
            "hash_lock": HASH_LOCK,
            "timeout_height": 1_000,
        },
        "amount": 50_000,
        "lock_block_height": 100,
        "state": "locked",
        "claim": None,
        "reclaim": None,
        "role": "observer",
        "last_indexed_height": 105,
    }


async def test_htlc_lock(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "tx_id": TX_ID,
                "output_index": 0,
                "size": 250,
                "fee": 1_000,
                "fee_rate": 4,
                "amount": 50_000,
                "change": 49_000,
                "submitted": True,
                "tip_height": 100,
            }
        )
    )
    out = await client.htlc_lock(
        from_=ADDR,
        receiver=PUBKEY_RECEIVER,
        hash_lock=HASH_LOCK,
        timeout=200,
        amount=50_000,
        fee_rate=4,
    )
    assert out["tx_id"] == TX_ID


async def test_htlc_lock_rejects_fee_and_fee_rate_together(client: AsyncClient) -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        await client.htlc_lock(
            from_=ADDR,
            receiver=PUBKEY_RECEIVER,
            hash_lock=HASH_LOCK,
            timeout=200,
            amount=50_000,
            fee=1_000,
            fee_rate=4,
        )


async def test_htlc_claim(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "tx_id": TX_ID,
                "size": 200,
                "fee": 500,
                "amount": 50_000,
                "submitted": True,
                "tip_height": 105,
            }
        )
    )
    out = await client.htlc_claim(
        from_=ADDR2,
        lock_tx_id=LOCK_TX_ID,
        preimage="aa" * 29,
        sender=ADDR,
        timeout=200,
    )
    assert out["amount"] == 50_000


async def test_htlc_reclaim(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "tx_id": TX_ID,
                "size": 180,
                "fee": 400,
                "amount": 50_000,
                "submitted": True,
                "tip_height": 250,
            }
        )
    )
    out = await client.htlc_reclaim(
        from_=ADDR,
        lock_tx_id=LOCK_TX_ID,
        receiver=PUBKEY_RECEIVER,
        hash_lock=HASH_LOCK,
        timeout=200,
    )
    assert out["tx_id"] == TX_ID


async def test_simulate_transfer(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "size": 250,
                "fee": 1_000,
                "fee_rate": 4,
                "inputs": [{"tx_id": TX_ID, "output_index": 1, "value": 100_000}],
                "outputs": [{"to": ADDR2, "amount": 50_000}],
                "total_in": 100_000,
                "total_out": 50_000,
                "change": 49_000,
                "built_at_height": 100,
            }
        )
    )
    out = await client.simulate_transfer(
        from_=ADDR,
        outputs=[{"to": ADDR2, "amount": 50_000}],
        fee_rate=4,
    )
    assert out["fee"] == 1_000


async def test_simulate_htlc_lock(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "size": 300,
                "fee": 1_200,
                "fee_rate": 4,
                "htlc_output_index": 0,
                "hash_lock": HASH_LOCK,
                "timeout": 200,
                "receiver": PUBKEY_RECEIVER,
                "amount": 50_000,
                "change": 49_000,
                "total_in": 100_000,
                "built_at_height": 100,
            }
        )
    )
    out = await client.simulate_htlc_lock(
        from_=ADDR,
        receiver=PUBKEY_RECEIVER,
        hash_lock=HASH_LOCK,
        timeout=200,
        amount=50_000,
    )
    assert out["htlc_output_index"] == 0


async def test_payment_uri_encode(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    expected = f"exfer:{ADDR}?amount=100000000"
    mock_walletd.post("/").mock(return_value=rpc_ok({"uri": expected}))
    out = await client.payment_uri_encode(address=ADDR, amount=100_000_000)
    assert out == expected


async def test_payment_uri_decode(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"address": ADDR, "amount": 100_000_000}))
    out = await client.payment_uri_decode(f"exfer:{ADDR}?amount=100000000")
    assert out["address"] == ADDR


async def test_htlc_status(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok(_htlc_record_fixture()))
    out = await client.htlc_status(LOCK_TX_ID)
    assert out["state"] == "locked"


async def test_htlc_list(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok({"htlcs": [_htlc_record_fixture()], "next_cursor": "abc"})
    )
    out = await client.htlc_list(role="receiver", state="locked")
    assert out["next_cursor"] == "abc"


async def test_htlc_forget(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"removed": True}))
    assert await client.htlc_forget(LOCK_TX_ID) is True


async def test_get_follower_status(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "last_indexed_height": 700,
                "last_indexed_block_id": BLOCK_HASH,
                "tip_height": 1_000,
                "lag": 300,
                "indexed_htlc_count": 5,
                "follower_started_at": 1_700_000_000,
                "full_scan_complete": False,
            }
        )
    )
    out = await client.get_follower_status()
    assert out["lag"] == 300


async def test_wait_for_tx(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "tx_id": TX_ID,
                "block_id": BLOCK_HASH,
                "block_height": 100,
                "confirmations": 1,
            }
        )
    )
    out = await client.wait_for_tx(TX_ID)
    assert out["confirmations"] == 1


async def test_wait_for_tx_timeout_error(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_err(-32040, "timed out"))
    with pytest.raises(WaitTimeoutError):
        await client.wait_for_tx(TX_ID, timeout_secs=10)


async def test_list_settlements(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "settlements": [
                    {
                        "tx_id": TX_ID,
                        "block_height": 200,
                        "contract_hash": "ee" * 32,
                        "outcome": "claimed",
                        "observer_address": ADDR,
                        "counterparty": ADDR2,
                        "amount": 50_000,
                        "lock_tx_id": LOCK_TX_ID,
                        "lock_output_index": 0,
                    }
                ]
            }
        )
    )
    out = await client.list_settlements(ADDR)
    assert out["settlements"][0]["outcome"] == "claimed"


async def test_list_settlements_indexer_not_configured(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_err(-32041, "indexer endpoint not configured on this walletd")
    )
    with pytest.raises(IndexerNotConfiguredError):
        await client.list_settlements(ADDR)


async def test_contract_stats(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "stats": [
                    {
                        "contract_hash": "ee" * 32,
                        "total": 3,
                        "succeeded": 2,
                        "refunded": 1,
                        "avg_settle_blocks": 8,
                        "last_settled_at_height": 250,
                    }
                ]
            }
        )
    )
    out = await client.contract_stats(ADDR)
    assert out[0]["total"] == 3


async def test_get_address_history(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "history": [
                    {
                        "block_height": 100,
                        "tx_id": TX_ID,
                        "amount": 1_000,
                        "direction": "output",
                        "is_coinbase": False,
                    }
                ]
            }
        )
    )
    out = await client.get_address_history(ADDR)
    assert out["history"][0]["direction"] == "output"


async def test_htlc_lookup_by_hashlock(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok({"htlcs": [_htlc_record_fixture(), _htlc_record_fixture()]})
    )
    out = await client.htlc_lookup_by_hashlock(HASH_LOCK)
    assert len(out) == 2


async def test_get_output_spent_by_spent(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "spent": True,
                "spending_tx_id": TX_ID,
                "input_index": 0,
                "block_height": 150,
                "source": "node",
            }
        )
    )
    out = await client.get_output_spent_by(LOCK_TX_ID, 0)
    assert out["spent"] is True


async def test_get_output_spent_by_unspent(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"spent": False, "source": "node"}))
    out = await client.get_output_spent_by(LOCK_TX_ID, 0)
    assert out["spent"] is False


# ---------------------------------------------------------------------------
# Honor layer — get_output_datum / find_settlements_by_quote_id / sim datum
# ---------------------------------------------------------------------------

QUOTE_ID = "0123456789abcdef0123456789abcdef"  # 16 bytes / 32 hex


async def test_get_output_datum_quote_id_hit(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    route = mock_walletd.post("/").mock(
        return_value=rpc_ok({"quote_id": QUOTE_ID, "unhonorable": False})
    )
    out = await client.get_output_datum(TX_ID, 2)
    assert out["quote_id"] == QUOTE_ID
    assert out["unhonorable"] is False
    body = json.loads(route.calls.last.request.content)
    assert body["params"] == {"tx_id": TX_ID, "output_index": 2}


async def test_get_output_datum_null_no_datum(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"quote_id": None, "unhonorable": False}))
    out = await client.get_output_datum(TX_ID, 0)
    assert out["quote_id"] is None
    assert out["unhonorable"] is False


async def test_find_settlements_by_quote_id_empty(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok({"settlements": []}))
    out = await client.find_settlements_by_quote_id(QUOTE_ID)
    assert out["settlements"] == []
    body = json.loads(route.calls.last.request.content)
    assert body["params"] == {"quote_id": QUOTE_ID}


async def test_find_settlements_by_quote_id_multi(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "settlements": [
                    {"tx_id": TX_ID, "output_index": 0},
                    {"tx_id": LOCK_TX_ID, "output_index": 3},
                ]
            }
        )
    )
    out = await client.find_settlements_by_quote_id(QUOTE_ID)
    assert len(out["settlements"]) == 2
    assert out["settlements"][1]["output_index"] == 3


async def test_simulate_transfer_includes_datum(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    route = mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "size": 245,
                "fee": 1_000,
                "fee_rate": 4,
                "inputs": [{"tx_id": TX_ID, "output_index": 1, "value": 100_000}],
                "outputs": [{"to": ADDR2, "amount": 50_000}],
                "total_in": 100_000,
                "total_out": 50_000,
                "change": 49_000,
                "built_at_height": 100,
            }
        )
    )
    out = await client.simulate_transfer(
        from_=ADDR,
        outputs=[{"to": ADDR2, "amount": 50_000}],
        fee_rate=4,
        datum=QUOTE_ID,
    )
    assert out["size"] == 245
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["datum"] == QUOTE_ID


# ---------------------------------------------------------------------------
# Cross-chain swap engine
# ---------------------------------------------------------------------------


def _swap_record_fixture() -> dict[str, object]:
    """A bnb_to_exfer SwapRecord (mirrors ``exfer-walletd/src/swap.rs``)."""
    return {
        "swap_id": "swap-abc123",
        "direction": "bnb_to_exfer",
        "status": "quoted",
        "amount_in": "0.05",
        "amount_out": "123.4",
        "expires_at": 1_700_000_300,
        "fee_bps": 30,
        "created_at": 1_700_000_000,
        "updated_at": 1_700_000_000,
    }


async def test_swap_get_quote_sends_params(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok(_swap_record_fixture()))
    out = await client.swap_get_quote(direction="bnb_to_exfer", amount_in="0.05", from_=ADDR)
    assert out["swap_id"] == "swap-abc123"
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "swap_get_quote"
    assert body["params"] == {"direction": "bnb_to_exfer", "amount_in": "0.05", "from": ADDR}


async def test_swap_execute_sends_swap_id(
    client: AsyncClient, mock_walletd: respx.MockRouter
) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok(_swap_record_fixture()))
    await client.swap_execute("swap-abc123")
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "swap_execute"
    assert body["params"] == {"swap_id": "swap-abc123"}


async def test_swap_list(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok([_swap_record_fixture()]))
    out = await client.swap_list()
    assert out[0]["swap_id"] == "swap-abc123"


async def test_bsc_get_address(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"address": "0xAbc", "created": True}))
    out = await client.bsc_get_address()
    assert out["address"] == "0xAbc"
    assert out["created"] is True


async def test_bsc_get_balances(client: AsyncClient, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok({"bnb_wei": "3505386683362864", "gas_reserve_wei": "200000000000000"})
    )
    out = await client.bsc_get_balances()
    assert out["bnb_wei"] == "3505386683362864"
    assert out["gas_reserve_wei"] == "200000000000000"
