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
       transport: httpx.BaseTransport | None = None)

AsyncClient(url, token, *, timeout=30.0, transport=None)
```

Alternate constructors:

```python
Client.from_env(*, url_env="WALLETD_URL", token_env="WALLETD_AUTH_TOKEN")
Client.from_datadir(*, url="http://127.0.0.1:8080", datadir="~/.exfer-walletd")
```

Both raise `RuntimeError` (`from_env`) or `FileNotFoundError`
(`from_datadir`) if the inputs are missing.

---

## `healthz() -> bool`

Probe `GET /healthz`. Returns `True` iff walletd answered `200 OK` with
body `ok`. **Returns `False` rather than raising** on any HTTP or
transport failure — suitable for liveness loops.

No `Authorization` header is sent (the endpoint is unauthenticated).

---

## Read-scope methods

### `ping() -> PingResult`

Liveness check that goes through the JSON-RPC envelope. Doesn't touch
the upstream node.

```python
{"ok": True}
```

### `generate_address() -> GenerateAddressResult`

Create a new Ed25519 keypair. Walletd persists the key on disk under
`<datadir>/wallets/<address>.key`.

```python
{
  "address": "27e1c8...",      # 64-char hex
  "pubkey":  "658f0a...",      # 64-char hex
}
```

### `list_addresses() -> list[str]`

Every address walletd holds a key for, sorted ascending.

Returns a bare list of hex strings — the wire envelope
`{"addresses": [...]}` is unwrapped at the SDK boundary.

### `get_balance(address: str) -> BalanceResult`

Confirmed balance for `address`, in exfers.

```python
{"address": "27e1c8...", "balance": 99900000}
```

Mempool UTXOs are not counted; for the mempool-aware view, use
`get_address_utxos`.

### `get_address_utxos(address: str) -> UtxosResult`

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

`truncated` is `True` if the upstream hit a result limit — paginate
client-side if you see this.

### `get_script_utxos(script_hex: str) -> UtxosResult`

Same shape as `get_address_utxos`, but matches by raw locking script
rather than address. `address` is always `None` in the result;
`script_hex` carries the queried script.

### `get_block_height() -> BlockHeightResult`

```python
{"height": 577429, "block_id": "17b95f..."}
```

### `get_block(*, height: int | None = None, hash: str | None = None) -> Block`

Fetch a block by height **or** hash. Exactly one must be set — passing
both or neither raises `TypeError` client-side (no HTTP round-trip).

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

### `get_transaction(hash: str) -> Transaction`

Fetch a transaction by its `tx_id`. Returns confirmed-chain or mempool
entries; `in_mempool` distinguishes.

```python
{
  "tx_id":        "a02ab0...",
  "tx_hex":       "01000200...",
  "in_mempool":   False,
  "block_hash":   "1bac70...",       # None if in mempool
  "block_height": 577429,            # None if in mempool
}
```

---

## Spend-scope methods

### `transfer(*, from_: str, to: str, amount: int, fee: int | None = None) -> TransferResult`

Build, sign, and broadcast a payment from a managed wallet.

- `from_` (trailing underscore) maps to the wire field `from`.
- `amount` and `fee` are in **exfers**.
- `fee` defaults to walletd's default (`100_000` = 0.001 EXFER) if
  omitted; pass an explicit integer to override.

```python
{
  "tx_id":      "a02ab0...",
  "size":       227,
  "tip_height": 577427,
  "submitted":  True,
}
```

Raises (most common):

- `WalletNotFoundError` — walletd doesn't hold the key for `from_`.
- `InsufficientBalanceError` — wallet can't cover `amount + fee`.
  Check `.in_flight_reserved` to decide whether to retry.
- `UpstreamError` — walletd's upstream node rejected the broadcast
  (e.g. double-spend) or is unreachable.
- `TxAuthError` — UTXO authentication failed; the upstream may be
  malicious or out of sync.

See [Errors](./errors.md) for the full list.

### `send_raw_transaction(tx_hex: str) -> SendRawResult`

Broadcast a pre-signed transaction. Used by `transfer` internally;
exposed for callers that build transactions externally.

```python
{"tx_id": "a02ab0..."}
```

---

## Type definitions

Every result type is a `typing.TypedDict` — zero runtime cost, full
type-checker coverage, and the wire dict carries forward unchanged if
walletd adds new fields.

```python
from exfer_walletd import (
    PingResult,
    GenerateAddressResult,
    BalanceResult,
    BlockHeightResult,
    Utxo,
    UtxosResult,
    Block,
    Transaction,
    TransferResult,
    SendRawResult,
)
```

Full field shapes are above under each method.
