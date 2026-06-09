# exfer-walletd (Python SDK)

Typed Python client for the [`exfer-walletd`](https://github.com/exfer-stack/exfer-walletd)
JSON-RPC API.

```bash
pip install exfer-walletd
```

```python
from exfer_walletd import Client

with Client("http://127.0.0.1:7448", token="...") as c:
    assert c.healthz()                # True
    res  = c.generate_address()       # {address, pubkey, index}
    addr = res["address"]
    bal  = c.get_balance(addr)        # int (exfers)

    tx = c.transfer(
        from_="<your-managed-address>",
        to="<recipient-address>",
        amount=30_000_000,            # exfers; 1 EXFER = 100_000_000 exfers
    )
    print(tx["tx_id"])
```

## What this is

- A thin, typed wrapper over walletd's JSON-RPC. One method per RPC method.
- Both sync (`Client`) and async (`AsyncClient`) — same surface, shared
  wire layer so they can't drift.
- Single-value endpoints return bare `str` / `int`. Multi-field
  endpoints return `TypedDict`s. No `pydantic` dependency.

## Async

```python
from exfer_walletd import AsyncClient

async with AsyncClient("http://127.0.0.1:7448", token) as c:
    assert await c.healthz()
    res  = await c.generate_address()  # {address, pubkey, index}
    print(await c.get_balance(res["address"]))
```

## What this isn't

- **Not a chain client.** This SDK talks to walletd, which talks to a
  node. It never holds keys, never signs transactions, never derives
  addresses. If you want client-side signing, run walletd.
- Not a high-level wallet abstraction. Methods map 1:1 to the wire
  grammar; build helpers on top as your application needs them.

## Token discovery

```python
# 1. Explicit
Client("http://127.0.0.1:7448", "your-token")

# 2. From env vars (deployed backends): WALLETD_URL + WALLETD_AUTH_TOKEN
Client.from_env()

# 3. From a local walletd datadir (dev / colocated)
Client.from_datadir()      # reads ~/.exfer-walletd/token
```

If walletd is configured with split scopes
(`WALLETD_AUTH_TOKEN_READ` + `WALLETD_AUTH_TOKEN_SPEND`), construct one
`Client` per scope. A read-only token calling `transfer` raises
`AuthenticationError`.

## Errors

Every documented walletd error code maps to a typed exception, all
rooted at `ExferError`:

```python
from exfer_walletd import (
    ExferError,               # blanket catch
    AuthenticationError,      # -32001
    WalletNotFoundError,      # -32010
    UpstreamError,            # -32020 — walletd's upstream node is unreachable
    TxAuthError,              # -32030 — UTXO authentication failed
    InsufficientBalanceError, # -32031 — wallet can't cover amount+fee
    InvalidParamsError,       # -32602
    TransportError,           # walletd itself unreachable / non-JSON body
)
```

`str(e)` is the `[-32xxx] message` form, so plain
`log.error(f"{e}")` is enough for production.

`InsufficientBalanceError.in_flight_reserved` is `True` when the
shortfall comes from UTXOs reserved by other pending transfers from the
same walletd — retry after they confirm.

## TLS

When walletd is started with `--tls` (v0.5.0+), point the SDK at the
`https://` URL and supply the fingerprint walletd printed on first
run:

```python
with Client.from_datadir(url="https://<walletd-host>:7448") as c:
    c.ping()          # auto-reads cert.fingerprint alongside token
```

The SDK pins the leaf cert by SHA-256, bypassing the CA chain
entirely. Mismatches raise `FingerprintMismatchError`.

## Docs

Full docs site: **<https://exfer-stack.github.io/exfer-py/>**.

## Status

`0.6.0` — alpha. Tested against `exfer-walletd >= 0.5.0` (TLS support).

MIT licensed.
