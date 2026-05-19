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

Raise `RuntimeError` (`from_env`) or `FileNotFoundError`
(`from_datadir`) if the inputs are missing.

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

### `generate_address() -> str`

Create a new managed address. Returns the address (lowercase 64-char
hex). Walletd persists the keypair on disk under
`<datadir>/wallets/<address>.key`.

### `list_addresses() -> list[str]`

Every address walletd holds a key for, sorted ascending.

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
from exfer_walletd import Tip

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

---

## Spend-scope methods

### `transfer(*, from_, to, amount, fee=None) -> TransferResult`

Build, sign, and broadcast a payment from a managed wallet.

- `from_` (trailing underscore) maps to wire field `from`.
- `amount`, `fee` are integers in **exfers**.
- Omitting `fee` lets walletd apply its default (100_000 = 0.001 EXFER).

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

---

## Type definitions

Single-value methods return bare Python types (`str`, `int`).
Multi-field methods return `TypedDict`s or `NamedTuple`s — import them
from `exfer_walletd.types` if you want to annotate variables.

```python
from exfer_walletd.types import (
    Block,
    Transaction,
    TransferResult,
    Utxo,
    UtxosResult,
)
from exfer_walletd import Tip       # NamedTuple — also top-level
```

You don't need to import any of these for normal use — they're just
return-type annotations.
