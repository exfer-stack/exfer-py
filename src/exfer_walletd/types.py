"""Result shapes for the SDK.

Field names and types track ``exfer-walletd/src/upstream/mod.rs`` and
``src/tx/mod.rs``.

Two flavours:

- ``TypedDict`` for multi-field responses where the wire dict carries
  multiple useful values (block, transaction, transfer receipt, utxo
  list). Zero runtime cost; mypy / pyright check perfectly.
- :class:`Tip` is a ``NamedTuple`` rather than a TypedDict because the
  common access pattern is positional unpacking (``height, block_id = ...``)
  and the field count is small enough to make that natural.

Amounts are integers in *exfers* (1 EXFER = 100_000_000 exfers).
Hash and address strings are lowercase hex, no ``0x`` prefix.
"""

from __future__ import annotations

from typing import NamedTuple, TypedDict

__all__ = [
    "Block",
    "Tip",
    "Transaction",
    "TransferResult",
    "Utxo",
    "UtxosResult",
]


class Tip(NamedTuple):
    """Chain tip — height and block hash together.

    Returned by :meth:`exfer_walletd.Client.get_tip` when you want both
    pieces of information. If you only need the height, call
    :meth:`get_block_height` instead and skip the unpack.
    """

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
