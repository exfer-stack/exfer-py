"""Sync-client tests for the walletd v1.9 + v1.9.1 method surface.

Each new method gets one happy-path round-trip plus, where the SDK does
non-trivial param construction or response unwrapping, one shape-asserting
test on the outgoing JSON body.

Wire shapes here track walletd v1.9.1's source — when walletd changes a
shape, these tests fail loudly rather than silently miscoding the wire.
"""

from __future__ import annotations

import json

import pytest
import respx

from exfer_walletd import Client, IndexerNotConfiguredError, WaitTimeoutError

from .conftest import rpc_err, rpc_ok

ADDR = "8b0609a812de3b0103dd3b3e78be4a99ef1699b6f02820e1bc1dbcfc75681481"
ADDR2 = "11" * 32
TX_ID = "a02ab025d75a295540d681f89da3f8bfed894e02cea721085facbf9ad4525c68"
LOCK_TX_ID = "cc" * 32
HASH_LOCK = "33" * 32
BLOCK_HASH = "17b95f159c3e51440207cc6648f655201bac84fd0e1e5a9ad8461e2d7a2932d5"
PUBKEY_RECEIVER = "22" * 32
PUBKEY_SENDER = "11" * 32


def _htlc_record_fixture() -> dict[str, object]:
    """Canonical HtlcRecord wire shape (mirrors
    ``exfer::covenants::htlc::HtlcRecord``)."""
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


# ---------------------------------------------------------------------------
# HTLC spend trio
# ---------------------------------------------------------------------------


def test_htlc_lock_sends_full_param_block(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(
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
    out = client.htlc_lock(
        from_=ADDR,
        receiver=PUBKEY_RECEIVER,
        hash_lock=HASH_LOCK,
        timeout=200,
        amount=50_000,
        fee_rate=4,
    )
    assert out["tx_id"] == TX_ID
    assert out["output_index"] == 0
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "htlc_lock"
    assert body["params"] == {
        "from": ADDR,
        "receiver": PUBKEY_RECEIVER,
        "hash_lock": HASH_LOCK,
        "timeout": 200,
        "amount": 50_000,
        "fee_rate": 4,
    }


def test_htlc_lock_rejects_fee_and_fee_rate_together(client: Client) -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        client.htlc_lock(
            from_=ADDR,
            receiver=PUBKEY_RECEIVER,
            hash_lock=HASH_LOCK,
            timeout=200,
            amount=50_000,
            fee=1_000,
            fee_rate=4,
        )


def test_htlc_claim_returns_receipt(client: Client, mock_walletd: respx.MockRouter) -> None:
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
    out = client.htlc_claim(
        from_=ADDR2,
        lock_tx_id=LOCK_TX_ID,
        preimage="aa" * 29,
        sender=ADDR,
        timeout=200,
    )
    assert out["tx_id"] == TX_ID
    assert out["amount"] == 50_000


def test_htlc_reclaim_returns_receipt(client: Client, mock_walletd: respx.MockRouter) -> None:
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
    out = client.htlc_reclaim(
        from_=ADDR,
        lock_tx_id=LOCK_TX_ID,
        receiver=PUBKEY_RECEIVER,
        hash_lock=HASH_LOCK,
        timeout=200,
    )
    assert out["tx_id"] == TX_ID


# ---------------------------------------------------------------------------
# Simulate (dry-run)
# ---------------------------------------------------------------------------


def test_simulate_transfer_round_trips(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(
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
    out = client.simulate_transfer(
        from_=ADDR,
        outputs=[{"to": ADDR2, "amount": 50_000}],
        fee_rate=4,
    )
    assert out["fee"] == 1_000
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["from"] == ADDR
    assert body["params"]["outputs"] == [{"to": ADDR2, "amount": 50_000}]


def test_simulate_htlc_lock_round_trips(client: Client, mock_walletd: respx.MockRouter) -> None:
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
    out = client.simulate_htlc_lock(
        from_=ADDR,
        receiver=PUBKEY_RECEIVER,
        hash_lock=HASH_LOCK,
        timeout=200,
        amount=50_000,
    )
    assert out["htlc_output_index"] == 0
    assert out["hash_lock"] == HASH_LOCK


# ---------------------------------------------------------------------------
# Payment URI codec
# ---------------------------------------------------------------------------


def test_payment_uri_encode_returns_string(client: Client, mock_walletd: respx.MockRouter) -> None:
    expected_uri = f"exfer:{ADDR}?amount=100000000&memo=invoice%2099"
    route = mock_walletd.post("/").mock(return_value=rpc_ok({"uri": expected_uri}))
    uri = client.payment_uri_encode(address=ADDR, amount=100_000_000, memo="invoice 99")
    assert uri == expected_uri
    body = json.loads(route.calls.last.request.content)
    # `label`, `hash_lock`, `timeout` were unset → must NOT appear on the wire.
    assert body["params"] == {"address": ADDR, "amount": 100_000_000, "memo": "invoice 99"}


def test_payment_uri_decode_returns_struct(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok({"address": ADDR, "amount": 100_000_000, "memo": "invoice 99"})
    )
    out = client.payment_uri_decode(f"exfer:{ADDR}?amount=100000000&memo=invoice%2099")
    assert out["address"] == ADDR
    assert out["amount"] == 100_000_000


# ---------------------------------------------------------------------------
# HTLC observability
# ---------------------------------------------------------------------------


def test_htlc_status_returns_record(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok(_htlc_record_fixture()))
    out = client.htlc_status(LOCK_TX_ID)
    assert out["state"] == "locked"
    assert out["params"]["hash_lock"] == HASH_LOCK


def test_htlc_list_omits_unset_filters(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok({"htlcs": [_htlc_record_fixture()]}))
    out = client.htlc_list(role="receiver", state=["locked", "claimed"])
    assert len(out["htlcs"]) == 1
    body = json.loads(route.calls.last.request.content)
    # `since_height`, `address`, `limit`, `cursor` unset → omitted from wire.
    assert body["params"] == {"role": "receiver", "state": ["locked", "claimed"]}


def test_htlc_list_propagates_next_cursor(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok({"htlcs": [_htlc_record_fixture()], "next_cursor": "abc"})
    )
    out = client.htlc_list(limit=1)
    assert out["next_cursor"] == "abc"


def test_htlc_forget_unwraps_removed(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"removed": True}))
    assert client.htlc_forget(LOCK_TX_ID) is True


def test_get_follower_status(client: Client, mock_walletd: respx.MockRouter) -> None:
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
    out = client.get_follower_status()
    assert out["lag"] == 300
    assert out["full_scan_complete"] is False


def test_wait_for_tx_returns_confirmations(client: Client, mock_walletd: respx.MockRouter) -> None:
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
    out = client.wait_for_tx(TX_ID)
    assert out["confirmations"] == 1


def test_wait_for_tx_raises_on_timeout(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_err(-32040, "wait_for_tx: timed out"))
    with pytest.raises(WaitTimeoutError):
        client.wait_for_tx(TX_ID, timeout_secs=10)


# ---------------------------------------------------------------------------
# Indexer-delegated
# ---------------------------------------------------------------------------


def test_list_settlements_returns_records(client: Client, mock_walletd: respx.MockRouter) -> None:
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
    out = client.list_settlements(ADDR)
    assert len(out["settlements"]) == 1
    assert out["settlements"][0]["outcome"] == "claimed"


def test_indexer_method_surfaces_typed_error_when_unconfigured(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_err(-32041, "indexer endpoint not configured on this walletd")
    )
    with pytest.raises(IndexerNotConfiguredError) as exc_info:
        client.list_settlements(ADDR)
    assert exc_info.value.code == -32041


def test_contract_stats_unwraps_list(client: Client, mock_walletd: respx.MockRouter) -> None:
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
    out = client.contract_stats(ADDR)
    assert out[0]["total"] == 3
    assert out[0]["succeeded"] == 2


def test_get_address_history_returns_rows(client: Client, mock_walletd: respx.MockRouter) -> None:
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
    out = client.get_address_history(ADDR)
    assert out["history"][0]["direction"] == "output"


def test_htlc_lookup_by_hashlock_unwraps_list(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok({"htlcs": [_htlc_record_fixture(), _htlc_record_fixture()]})
    )
    out = client.htlc_lookup_by_hashlock(HASH_LOCK)
    assert len(out) == 2


def test_get_output_spent_by_spent_branch(client: Client, mock_walletd: respx.MockRouter) -> None:
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
    out = client.get_output_spent_by(LOCK_TX_ID, 0)
    assert out["spent"] is True
    assert out["source"] == "node"


def test_get_output_spent_by_unspent_branch(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"spent": False, "source": "node"}))
    out = client.get_output_spent_by(LOCK_TX_ID, 0)
    assert out["spent"] is False
