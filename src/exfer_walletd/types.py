"""TypedDict result shapes for every walletd JSON-RPC method.

Field names and types track ``exfer-walletd/src/upstream/mod.rs`` and
``src/tx/mod.rs``. ``Optional[T]`` is used in the stdlib-y form rather
than ``T | None`` so the dicts stay readable on Python 3.9 without
``from __future__ import annotations`` polluting consumer files.

Amounts are integers in *exfers* (1 EXFER = 100_000_000 exfers).
Hash and address strings are lowercase hex, no ``0x`` prefix.
"""

from __future__ import annotations

from typing import TypedDict

__all__ = [
    "BalanceResult",
    "Block",
    "BlockHeightResult",
    "GenerateAddressResult",
    "PingResult",
    "SendRawResult",
    "Transaction",
    "TransferResult",
    "Utxo",
    "UtxosResult",
]


class PingResult(TypedDict):
    ok: bool


class GenerateAddressResult(TypedDict):
    address: str
    pubkey: str


class BalanceResult(TypedDict):
    address: str
    balance: int


class BlockHeightResult(TypedDict):
    height: int
    block_id: str


class Utxo(TypedDict):
    tx_id: str
    output_index: int
    value: int
    height: int
    is_coinbase: bool
    script_len: int | None


class UtxosResult(TypedDict):
    address: str | None
    script_hex: str | None
    tip_height: int
    truncated: bool
    utxos: list[Utxo]


class Block(TypedDict):
    hash: str
    height: int
    prev_block_id: str
    state_root: str
    tx_root: str
    timestamp: int
    nonce: int
    difficulty_target: str
    tx_count: int
    transactions: list[str]


class Transaction(TypedDict):
    tx_id: str
    tx_hex: str
    in_mempool: bool
    block_hash: str | None
    block_height: int | None


class TransferResult(TypedDict):
    tx_id: str
    size: int
    tip_height: int
    submitted: bool


class SendRawResult(TypedDict):
    tx_id: str
