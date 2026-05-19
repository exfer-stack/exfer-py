# Errors

The entire SDK error tree is rooted at `ExferError` — so a blanket
`except ExferError` always works as the outermost catch.

Underneath, two operational classes:

- **`WalletdError`** — walletd answered with a JSON-RPC error envelope.
  Every documented error code maps to a typed subclass.
- **`TransportError`** — walletd itself is unreachable, the body isn't
  JSON, or HTTP framing went sideways. Separate branch from
  `WalletdError`.

```python
from exfer_walletd import (
    ExferError,        # top-level catch-all
    WalletdError,      # walletd answered with an error
    TransportError,    # walletd unreachable / non-JSON / etc.
)

try:
    c.get_balance(addr)
except WalletdError as e:        # walletd answered with an error
    handle_rpc_error(e.code, e.message)
except TransportError as e:      # walletd unreachable, etc.
    handle_network_error(e)
except ExferError as e:          # belt-and-braces fallback
    log.exception("unexpected SDK error: %s", e)
```

`str(e)` always includes the code in the `[-32xxx] message` format,
so plain `log.error(f"{e}")` is enough for production logs.

## `FingerprintMismatchError`

A subclass of `TransportError`, raised when the TLS leaf cert presented
by the server doesn't match the SHA-256 fingerprint you pinned. Means
*some* walletd answered, but it isn't the walletd you configured —
typical causes: an MitM, the cert was regenerated server-side and the
operator forgot to update the client config, or the wrong fingerprint
was wired in. Always a hard fail; never retry.

```python
from exfer_walletd import Client, FingerprintMismatchError

try:
    with Client("https://walletd.internal:8443", token,
                fingerprint="sha256:b669...") as c:
        c.ping()
except FingerprintMismatchError as e:
    print("expected:", e.expected)
    print("got:     ", e.actual)
```

Because it inherits `TransportError` (and therefore `ExferError`),
existing `except TransportError` / `except ExferError` blocks catch it
automatically — adding the specific class lets you distinguish "wrong
walletd" from "walletd unreachable."

## Code → exception table

Every code below is a subclass of `WalletdError` (and therefore of
`ExferError`). Catch the narrow type when you have specific handling;
otherwise catch `WalletdError`.

| Code | Exception | When |
|------|-----------|------|
| `-32001` | `AuthenticationError` | Token missing, wrong, or scope insufficient for the method. Also raised on HTTP 401. |
| `-32010` | `WalletNotFoundError` | `from` address has no key file on walletd's disk. |
| `-32011` | `WalletExistsError` | Address collision on `generate_address` (cosmically rare). |
| `-32020` | `UpstreamError` | Walletd's upstream node is unreachable, or returned an RPC error (e.g. mempool rejection). Walletd has already retried before surfacing this. |
| `-32030` | `TxAuthError` | UTXO authentication failed — the upstream returned tx data that didn't match the outpoint walletd asked about. Often means the node is malicious or out of sync. |
| `-32031` | `InsufficientBalanceError` | Wallet can't cover `amount + fee`. See `.in_flight_reserved`. |
| `-32601` | `MethodNotFoundError` | Method name unknown to walletd. |
| `-32602` | `InvalidParamsError` | Bad hex, wrong address length, missing field, integer overflow. |
| `-32603` | `InternalError` | Walletd hit an unexpected internal error. |
| `-32700` | `ParseError` | Walletd couldn't parse the JSON-RPC envelope (HTTP 400). |

**Unknown codes** (a future walletd may add new ones) fall through to
bare `WalletdError` carrying the raw `code` and `message`, rather than
being silently swallowed. Callers can always branch on `e.code`.

## `InsufficientBalanceError.in_flight_reserved`

The one piece of value-add parsing the SDK does: when walletd's
shortfall comes from UTXOs reserved by *other* pending transfers from
the same daemon, `in_flight_reserved` is `True`. In that case
retrying in a few seconds may succeed (once the pending transfers
confirm and free their UTXOs).

```python
from exfer_walletd import InsufficientBalanceError

try:
    c.transfer(from_=hot, to=user, amount=1_000_000)
except InsufficientBalanceError as e:
    if e.in_flight_reserved:
        time.sleep(5)         # let pending transfers confirm
        retry(...)
    else:
        alert_ops("hot wallet drained")
```

The flag is sourced from the error envelope's `data` field when
walletd populates it; otherwise we fall back to string-matching
walletd's canonical message. On parse miss, defaults to `False` — the
safe choice so callers never blindly retry.

## HTTP framing

Walletd returns:

- **HTTP 401** for any auth failure → `AuthenticationError`
- **HTTP 400** for unparseable JSON → `ParseError`
- **HTTP 200** for everything else (success or JSON-RPC error)

Other status codes (5xx, redirects) are wrapped as `TransportError`.

## Common pitfalls

- **`TransportError` after `UpstreamError`**: walletd is up, but its
  *upstream node* is down. Check walletd's logs.
- **`AuthenticationError` on `transfer` only**: you constructed `Client`
  with a read-scope token. Use the spend-scope token, or split your
  service into a deposit-watcher (read) and a withdrawal-worker
  (spend) with separate clients.
- **`InvalidParamsError` with "invalid address"**: an upstream call got
  a non-hex or wrong-length string. Walletd validates inputs at the
  wrapper layer (added in walletd `v0.4.1`) so a typo'd address
  surfaces as `-32602` rather than a misleading `balance: 0`.
