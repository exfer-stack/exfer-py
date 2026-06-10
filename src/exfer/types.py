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
    "AddressRecord",
    "AttestationEdge",
    "AttestationEdgesResult",
    "Block",
    "ContractStatsRow",
    "DetectSwapsResult",
    "FollowerStatus",
    "GenerateAddressResult",
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
    "OutputDatum",
    "PaymentUri",
    "QuoteIssueResult",
    "QuoteJson",
    "QuoteVerifyResult",
    "SettlementOutpoint",
    "SettlementRecord",
    "SettlementsResult",
    "SignMessageResult",
    "SimulateHtlcLockResult",
    "SimulateTransferResult",
    "SpentByResult",
    "SwapGroup",
    "Tip",
    "Transaction",
    "TransferResult",
    "Utxo",
    "UtxosResult",
    "VerifyMessageResult",
    "WaitForPaymentResult",
    "WaitForTxResult",
]


class Tip(NamedTuple):
    """Chain tip — height and block hash together.

    Returned by :meth:`exfer.Client.get_tip` when you want both
    pieces of information. If you only need the height, call
    :meth:`get_block_height` instead and skip the unpack.
    """

    height: int
    block_id: str


class GenerateAddressResult(TypedDict):
    """Receipt from :meth:`Client.generate_address`.

    Carries the freshly-minted ``address`` together with the ``pubkey``
    walletd derived for it and its keystore ``index``. The ``pubkey``
    (64 hex) is the value to pass as ``payee_pubkey`` to
    :meth:`Client.quote_issue` — no separate lookup needed.
    """

    address: str  # hex64
    pubkey: str  # hex64
    index: int


class AddressRecord(TypedDict, total=False):
    """One entry from :meth:`Client.list_addresses`.

    ``address`` is always present. ``index`` is the keystore derivation
    index. Exactly one of ``label`` (a generated/managed key) or
    ``imported`` (``True`` for keys imported from outside walletd) is
    set per record, mirroring walletd's wire shape.
    """

    address: str  # hex64
    index: int
    label: str
    imported: bool


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


class SignMessageResult(TypedDict):
    signature: str  # hex128
    pubkey: str  # hex64
    address: str  # hex64


class VerifyMessageResult(TypedDict):
    valid: bool
    address: str  # address derived from pubkey (returned even on valid=false)


# ---------------------------------------------------------------------------
# EXFER-QUOTE — signed price credential (walletd Wave 2 / quote.rs)
# ---------------------------------------------------------------------------


class QuoteJson(TypedDict, total=False):
    # The canonical signed quote object (snake_case, lowercase hex). This is
    # both the ``quote_issue`` result body (``QuoteIssueResult.quote``) and
    # the ``quote_verify`` input. ``payer_pubkey`` is present only when the
    # quote was issued with a payer binding (non-transferable); all other
    # fields are always present.
    version: int
    quote_id: str  # 16 bytes / 32 hex
    currency: str  # 3-12 chars [A-Z0-9]
    amount_minor: int
    rate_exfers_per_unit: int
    exfer_amount: int  # the only binding amount, exfers
    payee_pubkey: str  # hex64
    payer_pubkey: str  # hex64; omitted when no payer binding
    issued_at: int
    expires_at: int
    memo: str  # UTF-8, <= 256 bytes
    signer_pubkey: str  # hex64
    signature: str  # hex128


class QuoteIssueResult(TypedDict):
    quote: QuoteJson  # the full signed quote credential to hand out
    signature: str  # hex128, also echoed in ``quote["signature"]``
    signer_address: str  # hex64, H(EXFER-ADDR, signer_pubkey)
    payee_address: str  # hex64, H(EXFER-ADDR, payee_pubkey)
    genesis_block_id: str  # hex64, live node genesis bound into the image
    image: str  # hex of the exact signed bytes, for audit
    htlc_preimage: str  # hex64, 32 random bytes — KEEP SECRET
    htlc_hash_lock: str  # hex64, SHA-256(htlc_preimage)


class QuoteVerifyResult(TypedDict, total=False):
    valid: bool
    reason: str  # why valid is false; omitted when valid
    signer_address: str  # hex64, derived from signer_pubkey (always present)
    payee_address: str  # hex64, derived from payee_pubkey (always present)
    genesis_block_id: str  # hex64, the live genesis checked against


class AttestationEdge(TypedDict, total=False):
    # One counterparty reputation edge for an address: how many contracts
    # ran between them and how they resolved. `contract_name` is present
    # only for recognised contract templates.
    counterparty: str
    contract_hash: str
    contract_name: str | None
    total: int
    succeeded: int
    refunded: int
    last_seen_height: int | None


class AttestationEdgesResult(TypedDict):
    edges: list[AttestationEdge]


class SwapGroup(TypedDict):
    # A set of HTLCs sharing one hash_lock — the on-chain fingerprint of
    # an atomic swap.
    hash_lock: str
    htlcs: list[HtlcRecord]


class DetectSwapsResult(TypedDict):
    swaps: list[SwapGroup]


class WaitForPaymentResult(TypedDict, total=False):
    # On a credit: ``received`` is True with ``tx_id`` / ``amount`` /
    # ``confirmations`` / ``tip_height``. On timeout: ``received`` is
    # False with ``timed_out`` True and ``waited_secs``. ``tx_id`` is
    # null when the credit was detected via a confirmed-balance delta
    # rather than a specific mempool tx.
    address: str
    received: bool
    timed_out: bool
    tx_id: str | None
    amount: int
    confirmations: int
    tip_height: int
    waited_secs: int


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


# ---------------------------------------------------------------------------
# Honor layer — datum read-back + settlement reverse-lookup (walletd proxies
# the indexer's strict 16-byte inline-datum index).
# ---------------------------------------------------------------------------


class OutputDatum(TypedDict):
    # The datum an output carries, as the indexer saw it.
    #
    # ``quote_id`` is non-null (32 hex / 16 bytes) iff the output carried a
    # strict 16-byte *inline* datum — the on-chain quote_id of a honor
    # settlement. ``unhonorable`` is True iff the output carried a
    # datum_hash-only commitment (the bytes weren't published inline, so the
    # quote_id can't be read back — the settlement can't be honor-verified).
    # An output with no datum at all yields ``{quote_id: None,
    # unhonorable: False}``: not a quote settlement, but not unhonorable either.
    quote_id: str | None
    unhonorable: bool


class SettlementOutpoint(TypedDict):
    # One on-chain output that settled a given quote_id.
    tx_id: str  # hex64
    output_index: int


class SettlementsResult(TypedDict):
    # Reverse-lookup result: every outpoint that paid a quote_id. Empty when
    # nothing on-chain references the quote_id yet; MAY hold more than one
    # outpoint (a quote could be settled more than once on-chain).
    settlements: list[SettlementOutpoint]
