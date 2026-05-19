"""Every Client method round-trips against a mocked walletd response."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx

from exfer_walletd import Client

from .conftest import TOKEN, WALLETD_URL, rpc_ok

ADDR = "8b0609a812de3b0103dd3b3e78be4a99ef1699b6f02820e1bc1dbcfc75681481"
TX_ID = "a02ab025d75a295540d681f89da3f8bfed894e02cea721085facbf9ad4525c68"
BLOCK_HASH = "17b95f159c3e51440207cc6648f655201bac84fd0e1e5a9ad8461e2d7a2932d5"


# ---------------------------------------------------------------------------
# Read scope
# ---------------------------------------------------------------------------


def test_ping(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"ok": True}))
    assert client.ping() == {"ok": True}


def test_generate_address(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"address": ADDR, "pubkey": "de" * 32}))
    out = client.generate_address()
    assert out["address"] == ADDR
    assert out["pubkey"] == "de" * 32


def test_list_addresses_unwraps(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"addresses": [ADDR, "ee" * 32]}))
    out = client.list_addresses()
    assert isinstance(out, list)
    assert out == [ADDR, "ee" * 32]


def test_get_balance(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok({"address": ADDR, "balance": 99900000}))
    out = client.get_balance(ADDR)
    assert out["balance"] == 99900000
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "get_balance"
    assert body["params"] == {"address": ADDR}


def test_get_address_utxos(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "address": ADDR,
                "script_hex": None,
                "tip_height": 577429,
                "truncated": False,
                "utxos": [
                    {
                        "tx_id": TX_ID,
                        "output_index": 1,
                        "value": 99900000,
                        "height": 577429,
                        "is_coinbase": False,
                        "script_len": None,
                    }
                ],
            }
        )
    )
    out = client.get_address_utxos(ADDR)
    assert out["tip_height"] == 577429
    assert out["truncated"] is False
    assert len(out["utxos"]) == 1
    assert out["utxos"][0]["value"] == 99900000


def test_get_script_utxos(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(
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
    out = client.get_script_utxos("deadbeef")
    assert out["script_hex"] == "deadbeef"
    body = json.loads(route.calls.last.request.content)
    assert body["params"] == {"script_hex": "deadbeef"}


def test_get_block_height(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(return_value=rpc_ok({"height": 1, "block_id": BLOCK_HASH}))
    out = client.get_block_height()
    assert out == {"height": 1, "block_id": BLOCK_HASH}


def _block_result() -> dict:
    return {
        "hash": BLOCK_HASH,
        "height": 577429,
        "prev_block_id": "00" * 32,
        "state_root": "11" * 32,
        "tx_root": "22" * 32,
        "timestamp": 1700000000,
        "nonce": 42,
        "difficulty_target": "ff" * 32,
        "tx_count": 1,
        "transactions": [TX_ID],
    }


def test_get_block_by_height(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok(_block_result()))
    out = client.get_block(height=577429)
    assert out["hash"] == BLOCK_HASH
    body = json.loads(route.calls.last.request.content)
    assert body["params"] == {"height": 577429}


def test_get_block_by_hash(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok(_block_result()))
    client.get_block(hash=BLOCK_HASH)
    body = json.loads(route.calls.last.request.content)
    assert body["params"] == {"hash": BLOCK_HASH}


def test_get_block_rejects_both() -> None:
    c = Client(WALLETD_URL, TOKEN)
    with pytest.raises(TypeError, match="exactly one"):
        c.get_block(height=1, hash=BLOCK_HASH)


def test_get_block_rejects_neither() -> None:
    c = Client(WALLETD_URL, TOKEN)
    with pytest.raises(TypeError, match="exactly one"):
        c.get_block()


def test_get_transaction(client: Client, mock_walletd: respx.MockRouter) -> None:
    mock_walletd.post("/").mock(
        return_value=rpc_ok(
            {
                "tx_id": TX_ID,
                "tx_hex": "01000200deadbeef",
                "in_mempool": False,
                "block_hash": BLOCK_HASH,
                "block_height": 577429,
            }
        )
    )
    out = client.get_transaction(TX_ID)
    assert out["tx_id"] == TX_ID
    assert out["in_mempool"] is False


# ---------------------------------------------------------------------------
# Spend scope
# ---------------------------------------------------------------------------


def test_transfer_wire_field_is_from_not_from_(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    route = mock_walletd.post("/").mock(
        return_value=rpc_ok({"tx_id": TX_ID, "size": 227, "tip_height": 577429, "submitted": True})
    )
    out = client.transfer(from_=ADDR, to="ee" * 32, amount=30000000)
    assert out["submitted"] is True
    body = json.loads(route.calls.last.request.content)
    assert body["method"] == "transfer"
    # Critical: wire field must be "from", not "from_".
    assert body["params"] == {"from": ADDR, "to": "ee" * 32, "amount": 30000000}


def test_transfer_with_fee(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(
        return_value=rpc_ok({"tx_id": TX_ID, "size": 227, "tip_height": 1, "submitted": True})
    )
    client.transfer(from_=ADDR, to="ee" * 32, amount=1, fee=42)
    body = json.loads(route.calls.last.request.content)
    assert body["params"]["fee"] == 42


def test_transfer_omits_fee_when_none(client: Client, mock_walletd: respx.MockRouter) -> None:
    """When fee is None, omit it so walletd uses its default (100_000)."""
    route = mock_walletd.post("/").mock(
        return_value=rpc_ok({"tx_id": TX_ID, "size": 227, "tip_height": 1, "submitted": True})
    )
    client.transfer(from_=ADDR, to="ee" * 32, amount=1)
    body = json.loads(route.calls.last.request.content)
    assert "fee" not in body["params"]


def test_send_raw_transaction(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok({"tx_id": TX_ID}))
    out = client.send_raw_transaction("01000200deadbeef")
    assert out == {"tx_id": TX_ID}
    body = json.loads(route.calls.last.request.content)
    assert body["params"] == {"tx_hex": "01000200deadbeef"}


# ---------------------------------------------------------------------------
# Alternate constructors
# ---------------------------------------------------------------------------


def test_from_env_reads_url_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WALLETD_URL", WALLETD_URL)
    monkeypatch.setenv("WALLETD_AUTH_TOKEN", "env-token")
    c = Client.from_env()
    assert c._url == WALLETD_URL
    assert c._token == "env-token"
    c.close()


def test_from_env_custom_var_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_URL", "http://other")
    monkeypatch.setenv("MY_TOK", "tok")
    c = Client.from_env(url_env="MY_URL", token_env="MY_TOK")
    assert c._token == "tok"
    c.close()


def test_from_env_missing_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WALLETD_URL", raising=False)
    monkeypatch.setenv("WALLETD_AUTH_TOKEN", "x")
    with pytest.raises(RuntimeError, match="WALLETD_URL"):
        Client.from_env()


def test_from_env_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WALLETD_URL", "x")
    monkeypatch.delenv("WALLETD_AUTH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="WALLETD_AUTH_TOKEN"):
        Client.from_env()


def test_from_datadir_reads_token_file(tmp_path: Path) -> None:
    (tmp_path / "token").write_text("file-token\n")
    c = Client.from_datadir(url="http://x", datadir=str(tmp_path))
    assert c._token == "file-token"
    c.close()


def test_from_datadir_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="token file not found"):
        Client.from_datadir(datadir=str(tmp_path))


def test_from_datadir_empty_token(tmp_path: Path) -> None:
    (tmp_path / "token").write_text("")
    with pytest.raises(RuntimeError, match="empty"):
        Client.from_datadir(datadir=str(tmp_path))


def test_from_datadir_expands_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".exfer-walletd").mkdir()
    (tmp_path / ".exfer-walletd" / "token").write_text("home-token")
    c = Client.from_datadir()
    assert c._token == "home-token"
    c.close()


def test_user_agent_header_sent(client: Client, mock_walletd: respx.MockRouter) -> None:
    route = mock_walletd.post("/").mock(return_value=rpc_ok({"ok": True}))
    client.ping()
    ua = route.calls.last.request.headers["user-agent"]
    assert ua.startswith("exfer-walletd-py/")
