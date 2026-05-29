"""Result shapes for the SDK.

Field names and types track ``exfer-walletd/src/upstream/mod.rs``,
``src/tx/mod.rs``, ``src/api/*.rs`` and the shared observer DTOs in
``exfer::covenants::htlc``.

Two flavours:

- ``TypedDict`` for multi-field responses where the wire dict carries
  multiple useful values (block, transaction, transfer receipt, HTLC
  record, settlement). Zero runtime cost; mypy / pyright check
  perfectly.
- :class:`Tip` is a ``NamedTuple`` rather than a TypedDict because the
  common access pattern is positional unpacking (``height, block_id = ...``)
  and the field count is small enough to make that natural.

Amounts are integers in *exfers* (1 EXFER = 100_000_000 exfers).
Hash and address strings are lowercase hex, no ``0x`` prefix.
"""

from __future__ import annotations

from typing import Literal, NamedTuple, TypedDict

__all__ = [
    "AddressHistoryResult",
    "AddressHistoryRow",
    "Block",
    "ContractStatsRow",
    "FollowerStatus",
    "HtlcClaimRecord",
    "HtlcClaimResult",
    "HtlcListResult",
    "HtlcLockResult",
    "HtlcParams",
    "HtlcReclaimRecord",
    "HtlcReclaimResult",
    "HtlcRecord",
    "HtlcRole",
    "HtlcState",
    "ListSettlementsResult",
    "PaymentUri",
    "SettlementRecord",
    "SimulateHtlcLockResult",
    "SimulateTransferResult",
    "SpentByResult",
    "Tip",
    "Transaction",
    "TransferResult",
    "Utxo",
    "UtxosResult",
    "WaitForTxResult",
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


# ---------------------------------------------------------------------------
# Shared HTLC observability shapes
# ---------------------------------------------------------------------------

# `HtlcState` and `HtlcRole` are Literal aliases rather than full enums so
# they cost nothing at runtime and TypedDict access narrows on them
# naturally. Wire spelling is snake_case (see
# `exfer::covenants::htlc::HtlcState` for the canonical list).
HtlcState = Literal["locked", "locked_expired", "claimed", "reclaimed", "unknown"]
HtlcRole = Literal["sender", "receiver", "both", "observer"]


class HtlcParams(TypedDict):
    sender: str
    receiver: str
    hash_lock: str
    timeout_height: int


class HtlcClaimRecord(TypedDict):
    tx_id: str
    # Variable-length lowercase hex. Empty string is valid (preimage of
    # zero bytes can satisfy a script that uses SHA-256(""), unusual but
    # legal). Length is `len(preimage) // 2` bytes.
    preimage: str
    block_height: int
    input_index: int


class HtlcReclaimRecord(TypedDict):
    tx_id: str
    block_height: int
    input_index: int


class HtlcRecord(TypedDict):
    lock_tx_id: str
    output_index: int
    params: HtlcParams
    amount: int
    # ``None`` when the lock is still in the mempool — wallet daemons
    # may register the HTLC optimistically before it confirms.
    lock_block_height: int | None
    state: HtlcState
    claim: HtlcClaimRecord | None
    reclaim: HtlcReclaimRecord | None
    role: HtlcRole
    last_indexed_height: int


# ---------------------------------------------------------------------------
# Spend-method receipts (walletd v1.7+ HTLC trio)
# ---------------------------------------------------------------------------


class HtlcLockResult(TypedDict):
    tx_id: str
    output_index: int
    size: int
    fee: int
    fee_rate: int
    amount: int
    change: int
    submitted: bool
    tip_height: int


class HtlcClaimResult(TypedDict):
    tx_id: str
    size: int
    fee: int
    amount: int
    submitted: bool
    tip_height: int


class HtlcReclaimResult(TypedDict):
    tx_id: str
    size: int
    fee: int
    amount: int
    submitted: bool
    tip_height: int


# ---------------------------------------------------------------------------
# Dry-run simulation receipts (v1.9)
# ---------------------------------------------------------------------------


class _SimInput(TypedDict):
    tx_id: str
    output_index: int
    value: int


class _SimOutput(TypedDict):
    to: str
    amount: int


class SimulateTransferResult(TypedDict):
    size: int
    fee: int
    fee_rate: int
    inputs: list[_SimInput]
    outputs: list[_SimOutput]
    total_in: int
    total_out: int
    change: int
    built_at_height: int


class SimulateHtlcLockResult(TypedDict):
    size: int
    fee: int
    fee_rate: int
    htlc_output_index: int
    hash_lock: str
    timeout: int
    receiver: str
    amount: int
    change: int
    total_in: int
    built_at_height: int


# ---------------------------------------------------------------------------
# Follower / wait / payment URI (v1.9)
# ---------------------------------------------------------------------------


class FollowerStatus(TypedDict):
    last_indexed_height: int
    last_indexed_block_id: str
    tip_height: int
    # `tip_height - last_indexed_height`. Treat <0 as 0 (brief races
    # between the tip RPC and the follower tick).
    lag: int
    indexed_htlc_count: int
    follower_started_at: int
    full_scan_complete: bool


class WaitForTxResult(TypedDict):
    tx_id: str
    block_id: str
    block_height: int
    confirmations: int


class PaymentUri(TypedDict, total=False):
    # `address` is the only required field; others are present iff they
    # were set in the URI / the encode call.
    address: str
    amount: int
    memo: str
    hash_lock: str
    timeout: int
    label: str


# ---------------------------------------------------------------------------
# Indexer-delegated shapes (walletd v1.9.1 proxies)
# ---------------------------------------------------------------------------

# Settlement outcome is a narrower subset of HtlcState (only the two
# terminal outcomes). Kept narrow so consumers can `match` on it without
# a fallthrough branch for transient states.
SettlementOutcome = Literal["claimed", "reclaimed"]


class SettlementRecord(TypedDict):
    tx_id: str
    block_height: int
    contract_hash: str
    outcome: SettlementOutcome
    observer_address: str
    counterparty: str
    amount: int
    lock_tx_id: str
    lock_output_index: int


class ListSettlementsResult(TypedDict, total=False):
    settlements: list[SettlementRecord]
    next_cursor: str


class ContractStatsRow(TypedDict, total=False):
    contract_hash: str
    total: int
    succeeded: int
    refunded: int
    avg_settle_blocks: int
    last_settled_at_height: int


# `direction` is `"input"` (the address spent this entry) or `"output"`
# (the address received this entry). Future direction tags may surface
# for contract-internal events.
TxDirection = Literal["input", "output"]


class AddressHistoryRow(TypedDict):
    block_height: int
    tx_id: str
    amount: int
    direction: TxDirection
    is_coinbase: bool


class AddressHistoryResult(TypedDict, total=False):
    history: list[AddressHistoryRow]
    next_cursor: str


class HtlcListResult(TypedDict, total=False):
    htlcs: list[HtlcRecord]
    next_cursor: str


# `source` distinguishes who answered the spent-by lookup:
# `"indexer-cache"` (walletd's own index), `"node"` (the upstream node's
# spent_by table from PR #21), or `"fallback-unknown-method"` (older
# node binary without the method — answer treated as "spent: false").
SpentBySource = Literal["indexer-cache", "node", "fallback-unknown-method"]


class SpentByResult(TypedDict, total=False):
    spent: bool
    spending_tx_id: str
    input_index: int
    block_height: int
    source: SpentBySource
