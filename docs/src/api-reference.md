# API reference

Every method exists on both `Client` (sync) and `AsyncClient` (async)
with identical names, parameters, and return shapes. The async version
is `async def` and must be `await`ed; otherwise they're interchangeable.

Amounts are integers in **exfers**, where `1 EXFER = 100_000_000 exfers`.
Hex strings (addresses, hashes, scripts, tx bytes) are lowercase, no
`0x` prefix.

---

## Construction

```python
Client(url: str, token: str, *, timeout: float = 30.0,
       transport: httpx.BaseTransport | None = None,
       fingerprint: str | None = None)

AsyncClient(url, token, *, timeout=30.0, transport=None, fingerprint=None)
```

`fingerprint` enables TLS pinning when walletd is run with `--tls`.
Format is `"sha256:<lowercase-hex-64>"` (the exact string walletd
writes to `<datadir>/cert.fingerprint` on first run). Requires an
`https://` URL. The pinning transport replaces CA-chain validation —
walletd's leaf cert is trusted iff its SHA-256 matches.

`transport=` and `fingerprint=` are mutually exclusive — the latter
installs a pinning transport itself, and accepting a custom one
alongside would silently bypass verification.

Alternate constructors:

```python
Client.from_env(*, url_env="WALLETD_URL",
                token_env="WALLETD_AUTH_TOKEN",
                fingerprint_env="WALLETD_FINGERPRINT")

Client.from_datadir(*, url="http://127.0.0.1:7448",
                    datadir="~/.exfer-walletd")
```

`from_env` reads `WALLETD_FINGERPRINT` if set (otherwise plaintext
HTTP). `from_datadir` auto-reads `<datadir>/cert.fingerprint` when
`url` is `https://`, raising `FileNotFoundError` if walletd hasn't
been started with `--tls` yet.

Raise `RuntimeError` (`from_env`) or `FileNotFoundError`
(`from_datadir`) if the required inputs are missing.

---

## Liveness

### `healthz() -> bool`

Probe `GET /healthz` — TCP+HTTP only. Returns `True` iff walletd
answered `200 OK` with body `ok`. **Returns `False` on any failure**
rather than raising — drops cleanly into liveness loops.

No `Authorization` header is sent. A green `healthz` says nothing
about whether your token is valid or whether walletd's upstream node
is reachable.

### `ping() -> None`

Authenticated JSON-RPC round-trip. Returns `None` on success and
raises on any failure. Use this when you want to verify the token is
valid and walletd's RPC layer is up — not just the TCP socket.

---

## Read-scope methods

### `generate_address() -> GenerateAddressResult`

Create a new managed address. Returns a `GenerateAddressResult` —
`{"address", "pubkey", "index"}` (address and pubkey are lowercase
64-char hex). The `pubkey` is the value to pass as `payee_pubkey` to
`quote_issue`. Walletd persists the keypair on disk under
`<datadir>/wallets/<address>.key`.

### `list_addresses() -> list[AddressRecord]`

Every address walletd holds a key for, sorted ascending. Each
`AddressRecord` is `{"address", "index", and one of "label"/"imported"}`.

### `get_balance(address: str) -> int`

Confirmed balance for `address`, in exfers. Mempool UTXOs are not
counted; for the mempool-aware view, use `get_address_utxos`.

### `get_address_utxos(address: str) -> UtxosResult`

Confirmed UTXOs locked to `address` plus tip metadata:

```python
{
  "address":    "27e1c8...",
  "script_hex": None,
  "tip_height": 577429,
  "truncated":  False,
  "utxos": [
    {
      "tx_id":        "a02ab0...",
      "output_index": 1,
      "value":        69900000,
      "height":       577429,
      "is_coinbase":  False,
      "script_len":   None,
    },
  ],
}
```

`truncated` is `True` if the upstream hit a result limit.

### `get_script_utxos(script_hex: str) -> UtxosResult`

Same shape as `get_address_utxos`, but matches by raw locking script.
`address` is always `None` in the result.

### `get_block_height() -> int`

Current chain tip height. For the (height, block_id) pair, use
`get_tip()`.

### `get_tip() -> Tip`

Current chain tip as a `NamedTuple`:

```python
from exfer import Tip

tip = c.get_tip()
print(tip.height, tip.block_id)
h, b = tip                    # unpack works too
```

### `get_block_by_height(height: int) -> Block`

```python
{
  "hash":              "17b95f...",
  "height":            577429,
  "prev_block_id":     "...",
  "state_root":        "...",
  "tx_root":           "...",
  "timestamp":         1700000000,
  "nonce":             42,
  "difficulty_target": "...",
  "tx_count":          1,
  "transactions":      ["a02ab0..."],
}
```

### `get_block_by_hash(block_hash: str) -> Block`

Same shape; lookup by block hash instead of height.

### `get_transaction(tx_id: str) -> Transaction`

Fetch a transaction. Covers mempool + confirmed; `in_mempool`
distinguishes.

```python
{
  "tx_id":        "a02ab0...",
  "tx_hex":       "01000200...",
  "in_mempool":   False,
  "block_hash":   "1bac70...",       # None if in mempool
  "block_height": 577429,            # None if in mempool
}
```

### `quote_verify(quote: QuoteJson) -> QuoteVerifyResult`

Accept-check a signed EXFER-QUOTE. Pure and key-free (Read scope):
reconstructs the signing image against the live node genesis and clock,
then checks the signature, key validity, and TTL/skew/expiry windows.
`quote` is the signed quote object (the `quote` field of a `quote_issue`
result).

```python
{
  "valid":            True,
  "reason":           "...",   # present only when valid is False
  "signer_address":   "...",   # derived from signer_pubkey — always present
  "payee_address":    "...",   # derived from payee_pubkey — always present
  "genesis_block_id": "...",   # the live genesis checked against
}
```

Proves authorship, not authority — the acceptor still decides whether it
trusts the signer.

---

## Spend-scope methods

### `transfer(*, from_, to, amount, fee=None, datum=None) -> TransferResult`

Build, sign, and broadcast a payment from a managed wallet.

- `from_` (trailing underscore) maps to wire field `from`.
- `amount`, `fee` are integers in **exfers**.
- Omitting `fee` lets walletd apply its default (100_000 = 0.001 EXFER).
- `datum` (hex, <= 4096 bytes) is an app-defined on-chain blob attached
  to the output; read it back via `get_transaction` / `get_output_datum`.

```python
{
  "tx_id":      "a02ab0...",
  "size":       227,
  "tip_height": 577427,
  "submitted":  True,
}
```

Common errors:

- `WalletNotFoundError` — walletd doesn't hold the key for `from_`.
- `InsufficientBalanceError` — check `.in_flight_reserved` to decide
  whether to retry.
- `UpstreamError` — node rejected the broadcast or is unreachable.
- `TxAuthError` — UTXO authentication failed; the upstream may be
  malicious or out of sync.

See [Errors](./errors.md) for the full list.

### `send_raw_transaction(tx_hex: str) -> str`

Broadcast a pre-signed transaction. Returns the broadcast `tx_id`.
Used by `transfer` internally; exposed for callers that build
transactions externally.

### `htlc_lock(*, from_, receiver, hash_lock, timeout, amount, fee=None, fee_rate=None, max_fee=None) -> HtlcLockResult`

Lock `amount` exfers from `from_` into a new HTLC output. `receiver` is
the receiver's 32-byte pubkey (64 hex); `timeout` is the absolute block
height past which `from_` can reclaim. `fee` and `fee_rate` are mutually
exclusive (passing both raises `ValueError`); omit both to let walletd
pick its default rate.

```python
{
  "tx_id":        "...",
  "output_index": 0,        # save this — every HTLC op needs it
  "size":         231,
  "fee":          100000,
  "fee_rate":     1,
  "amount":       30000000,
  "change":       69900000,
  "submitted":    True,
  "tip_height":   577429,
}
```

### `htlc_claim(*, from_, lock_tx_id, preimage, sender, timeout, output_index=0, fee=None) -> HtlcClaimResult`

Spend an HTLC via the hash arm by revealing `preimage` (hex, any
length). `from_` is the receiver wallet that claims the funds; `sender`
and `timeout` reconstruct the original locking script.

```python
{
  "tx_id":      "...",
  "size":       192,
  "fee":        100000,
  "amount":     29900000,
  "submitted":  True,
  "tip_height": 577430,
}
```

### `htlc_reclaim(*, from_, lock_tx_id, receiver, hash_lock, timeout, output_index=0, fee=None) -> HtlcReclaimResult`

Reclaim an expired HTLC via the timeout arm. `from_` is the original
sender. Walletd checks the chain tip and refuses to broadcast while
`current_height <= timeout`. Same result shape as `htlc_claim`.

### `quote_issue(*, address, payee_pubkey, currency, amount_minor, rate_exfers_per_unit, exfer_amount, ttl_secs, payer_pubkey=None, memo=None, quote_id=None) -> QuoteIssueResult`

Construct and sign an EXFER-QUOTE — a signed price credential (Spend
scope; mints a credential).

- `address` is the issuer/signer wallet whose key signs the image.
- `payee_pubkey` (64 hex) is the party to be paid.
- `currency` is a 3-12 char `[A-Z0-9]` pricing-unit code; `exfer_amount`
  is the only binding amount (exfers).
- `ttl_secs` sets the lifetime (`0 < ttl_secs <= 3600`).
- `payer_pubkey` (64 hex), when given, binds the quote to a payer
  (non-transferable). `memo` is a signed UTF-8 note (<= 256 bytes).
  `quote_id` (32 hex) pins the id; omitted means walletd generates 16
  random bytes.

```python
{
  "quote":            { ... },   # full signed QuoteJson to hand out
  "signature":        "...",     # hex128
  "signer_address":   "...",
  "payee_address":    "...",
  "genesis_block_id": "...",
  "image":            "...",     # hex of the exact signed bytes, for audit
  "htlc_preimage":    "...",     # hex64 — KEEP SECRET
  "htlc_hash_lock":   "...",     # hex64, SHA-256(htlc_preimage)
}
```

---

## Dry-run simulation

Read-scope. Both methods compute the exact `(size, fee, fee_rate, ...)`
a real call would produce — no broadcast, no UTXO reservation — so an
agent can prove a cost ceiling before committing to spend.

### `simulate_transfer(*, from_, outputs, fee=None, fee_rate=None, max_fee=None, datum=None) -> SimulateTransferResult`

Dry-run version of `transfer`. `outputs` is a list of
`{"to": addr_hex, "amount": exfers}` (up to 16 entries). `fee` and
`fee_rate` are mutually exclusive. `datum` (hex, even length, <= 4096
bytes) sizes the simulated tx *with* the datum bytes — pass the quote_id
you intend to attach so the dry-run matches the real settlement transfer.

```python
{
  "size":            227,
  "fee":             100000,
  "fee_rate":        1,
  "inputs":          [{"tx_id": "...", "output_index": 1, "value": 69900000}],
  "outputs":         [{"to": "...", "amount": 30000000}],
  "total_in":        69900000,
  "total_out":       30000000,
  "change":          39800000,
  "built_at_height": 577429,
}
```

### `simulate_htlc_lock(*, from_, receiver, hash_lock, timeout, amount, fee=None, fee_rate=None, max_fee=None) -> SimulateHtlcLockResult`

Dry-run version of `htlc_lock`. Same parameters; no broadcast, no
reservation.

```python
{
  "size":              231,
  "fee":               100000,
  "fee_rate":          1,
  "htlc_output_index": 0,
  "hash_lock":         "...",
  "timeout":           577500,
  "receiver":          "...",
  "amount":            30000000,
  "change":            39800000,
  "total_in":          69900000,
  "built_at_height":   577429,
}
```

---

## Payment URI codec

Pure, no I/O. BIP21-style `exfer:<address>?amount=...&memo=...` round trip.

### `payment_uri_encode(*, address, amount=None, memo=None, hash_lock=None, timeout=None, label=None) -> str`

Build an `exfer:` URI. Unset fields are omitted. Returns the URI string.

### `payment_uri_decode(uri: str) -> PaymentUri`

Parse an `exfer:` URI back into its components. `address` is always
present; the rest appear only if set in the URI.

```python
{
  "address":   "...",
  "amount":    30000000,   # present only if set
  "memo":      "...",
  "hash_lock": "...",
  "timeout":   577500,
  "label":     "...",
}
```

---

## Message signing

### `sign_message(address: str, message: str) -> SignMessageResult`

Sign an arbitrary UTF-8 message with `address`'s key, domain-separated
under EXFER-MSG. Proof of key control for off-chain
challenge-response / agent identity.

```python
{
  "signature": "...",   # hex128
  "pubkey":    "...",   # hex64
  "address":   "...",   # hex64
}
```

### `verify_message(pubkey: str, signature: str, message: str, *, address=None) -> VerifyMessageResult`

Verify a message signature (pure crypto). If `address` is given, `valid`
is true only when it also matches `H(pubkey)`.

```python
{
  "valid":   True,
  "address": "...",   # address derived from pubkey — returned even when valid is False
}
```

---

## HTLC observability

Walletd's own owned-key index (v1.9). For arbitrary (non-owned)
addresses, run walletd with `--indexer-rpc` so these route through the
multi-tenant index.

### `htlc_status(lock_tx_id: str, output_index: int = 0) -> HtlcRecord`

Current `HtlcRecord` for a lock outpoint. Raises `WalletdError` if
walletd tracks no HTLC there.

```python
{
  "lock_tx_id":          "...",
  "output_index":        0,
  "params":              {"sender": "...", "receiver": "...",
                          "hash_lock": "...", "timeout_height": 577500},
  "amount":              30000000,
  "lock_block_height":   577429,   # None while still in the mempool
  "state":               "locked", # locked | locked_expired | claimed | reclaimed | unknown
  "claim":               None,     # HtlcClaimRecord once claimed
  "reclaim":             None,     # HtlcReclaimRecord once reclaimed
  "role":                "sender", # sender | receiver | both | observer
  "last_indexed_height": 577429,
}
```

### `htlc_list(*, role=None, state=None, since_height=None, address=None, limit=None, cursor=None) -> HtlcListResult`

List HTLCs matching the filter, paginated. `state` accepts a single
`HtlcState` or a list of them; `role` filters on observer relationship.

```python
{
  "htlcs":       [ { ...HtlcRecord... } ],
  "next_cursor": "...",   # present only when more pages exist
}
```

### `htlc_forget(lock_tx_id: str, output_index: int = 0) -> bool`

Remove a settled HTLC entry from walletd's index. Only Claimed /
Reclaimed entries may be forgotten; pending ones raise `WalletdError`.
Returns `True` if an entry was removed, `False` if nothing was tracked
there.

### `get_follower_status() -> FollowerStatus`

Snapshot of walletd's block-follower state — height, lag, counts.

```python
{
  "last_indexed_height":   577429,
  "last_indexed_block_id": "...",
  "tip_height":            577429,
  "lag":                   0,        # tip_height - last_indexed_height; treat <0 as 0
  "indexed_htlc_count":    3,
  "follower_started_at":   1700000000,
  "full_scan_complete":    True,
}
```

### `wait_for_tx(tx_id: str, *, min_confirmations=1, timeout_secs=60) -> WaitForTxResult`

Block until `tx_id` has `min_confirmations` behind it. `timeout_secs` is
clamped server-side at 600. On timeout raises `WaitTimeoutError` — not a
terminal failure of the tx, which may still confirm later.

```python
{
  "tx_id":         "...",
  "block_id":      "...",
  "block_height":  577430,
  "confirmations": 1,
}
```

### `wait_for_payment(address: str, *, min_amount=1, timeout_secs=60) -> WaitForPaymentResult`

Block until a new credit of at least `min_amount` reaches `address`.
Returns as soon as the payment is *seen* in the mempool (0
confirmations) — a receipt/liveness signal, not settlement finality.
`timeout_secs` is clamped server-side at 600. A quiet window is not an
error: on timeout `received` is False and `timed_out` is True, so just
call again.

```python
{
  "address":       "...",
  "received":      True,
  "timed_out":     False,
  "tx_id":         "...",   # None when detected via a confirmed-balance delta
  "amount":        30000000,
  "confirmations": 0,
  "tip_height":    577429,
  "waited_secs":   2,
}
```

---

## Indexer-delegated queries

Multi-tenant queries (v1.9.1) that proxy an `exfer-indexer`. These
require walletd to be started with `--indexer-rpc`; otherwise they raise
`IndexerNotConfiguredError`.

### `list_settlements(address, *, contract_hash=None, since_height=None, limit=None, cursor=None) -> ListSettlementsResult`

History of settled HTLCs involving `address`.

```python
{
  "settlements": [
    {
      "tx_id":             "...",
      "block_height":      577430,
      "contract_hash":     "...",
      "outcome":           "claimed",   # claimed | reclaimed
      "observer_address":  "...",
      "counterparty":      "...",
      "amount":            30000000,
      "lock_tx_id":        "...",
      "lock_output_index": 0,
    },
  ],
  "next_cursor": "...",   # present only when more pages exist
}
```

### `contract_stats(address, *, contract_hash=None) -> list[ContractStatsRow]`

Aggregate stats per contract type for `address`. Without `contract_hash`,
one row per distinct contract the address has settled; with it, a single
row (or empty list) for that contract.

```python
[
  {
    "contract_hash":           "...",
    "total":                   12,
    "succeeded":               10,
    "refunded":                2,
    "avg_settle_blocks":       6,
    "last_settled_at_height":  577430,
  },
]
```

### `get_address_history(address, *, since_height=None, limit=None, cursor=None) -> AddressHistoryResult`

Activity timeline for `address` — every input + output it appears in.

```python
{
  "history": [
    {
      "block_height": 577430,
      "tx_id":        "...",
      "amount":       30000000,
      "direction":    "output",   # input | output
      "is_coinbase":  False,
    },
  ],
  "next_cursor": "...",   # present only when more pages exist
}
```

### `get_attestation_edges(address, *, contract_hash=None) -> AttestationEdgesResult`

Per-counterparty reputation edges for `address` (contracts run,
succeeded, refunded) — the on-chain trust signal to check before
transacting with a counterparty.

```python
{
  "edges": [
    {
      "counterparty":    "...",
      "contract_hash":   "...",
      "contract_name":   None,        # set only for recognised templates
      "total":           5,
      "succeeded":       4,
      "refunded":        1,
      "last_seen_height": 577430,
    },
  ],
}
```

### `detect_in_chain_swaps(*, hash_lock=None, limit=None) -> DetectSwapsResult`

Groups of HTLCs sharing a `hash_lock` — the atomic-swap fingerprint.

```python
{
  "swaps": [
    {"hash_lock": "...", "htlcs": [ { ...HtlcRecord... } ]},
  ],
}
```

### `htlc_lookup_by_hashlock(hash_lock: str) -> list[HtlcRecord]`

Every tracked HTLC committed to `hash_lock` — the canonical atomic-swap
fingerprint. Returns a list of `HtlcRecord` (see `htlc_status`).

### `get_output_spent_by(tx_id: str, output_index: int) -> SpentByResult`

Reverse-spend lookup: which tx spent `(tx_id, output_index)`? `source`
reveals where the answer came from (`"indexer-cache"`, `"node"`, or
`"fallback-unknown-method"` for older nodes). `spent: false` means
nobody has spent it given the indexer's current view.

```python
{
  "spent":          True,
  "spending_tx_id": "...",
  "input_index":    0,
  "block_height":   577430,
  "source":         "indexer-cache",
}
```

### `get_output_datum(tx_id: str, output_index: int) -> OutputDatum`

Read the datum an output carries — the honor *verify* step. A non-null
`quote_id` (32 hex) means the 16-byte inline datum was indexed and the
settlement is honor-verifiable. `unhonorable` is True for a
datum_hash-only output. No datum gives `{quote_id: None, unhonorable: False}`.

```python
{
  "quote_id":    "...",   # None if the output carries no inline quote_id
  "unhonorable": False,
}
```

### `find_settlements_by_quote_id(quote_id: str) -> SettlementsResult`

Reverse-lookup the on-chain outpoint(s) that settled `quote_id` (32 hex /
16 bytes) — the honor gate's first step. Zero entries when nothing
references the quote yet; more than one if it was settled multiple times.
Pair each outpoint with `get_output_datum` to verify the inline quote_id
read-back.

```python
{
  "settlements": [
    {"tx_id": "...", "output_index": 0},
  ],
}
```

---

## Type definitions

Single-value methods return bare Python types (`str`, `int`).
Multi-field methods return `TypedDict`s or `NamedTuple`s — import them
from `exfer.types` if you want to annotate variables.

```python
from exfer.types import (
    AddressHistoryResult,
    AddressRecord,
    AttestationEdgesResult,
    Block,
    ContractStatsRow,
    DetectSwapsResult,
    FollowerStatus,
    GenerateAddressResult,
    HtlcClaimResult,
    HtlcListResult,
    HtlcLockResult,
    HtlcReclaimResult,
    HtlcRecord,
    ListSettlementsResult,
    OutputDatum,
    PaymentUri,
    QuoteIssueResult,
    QuoteJson,
    QuoteVerifyResult,
    SettlementsResult,
    SignMessageResult,
    SimulateHtlcLockResult,
    SimulateTransferResult,
    SpentByResult,
    Transaction,
    TransferResult,
    Utxo,
    UtxosResult,
    VerifyMessageResult,
    WaitForPaymentResult,
    WaitForTxResult,
)
from exfer import Tip       # NamedTuple — also top-level
```

You don't need to import any of these for normal use — they're just
return-type annotations. `HtlcState` and `HtlcRole` are `Literal`
aliases, also in `exfer.types`.
