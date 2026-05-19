# exfer-walletd (Python SDK)

Typed Python client for the [`exfer-walletd`](https://github.com/exfer-stack/exfer-walletd)
JSON-RPC API.

```bash
pip install exfer-walletd
```

```python
from exfer_walletd import Client

with Client("http://127.0.0.1:8080", token="...") as c:
    print(c.healthz())                     # True if walletd is alive
    print(c.ping())                        # {"ok": True}

    addr = c.generate_address()["address"]
    print(c.get_balance(addr))             # {"address": "...", "balance": 0}

    tx = c.transfer(
        from_="<your-managed-address>",
        to="<recipient-address>",
        amount=30_000_000,                 # exfers; 1 EXFER = 100_000_000 exfers
    )
    print(tx["tx_id"])
```

## What this is

- A thin, typed wrapper over walletd's JSON-RPC. One method per RPC method.
- Sync today; async client lands in 0.2.
- Stdlib-only return types (`TypedDict`). Zero runtime overhead, full
  mypy/pyright support, no `pydantic` dependency forced on consumers.

## What this isn't

- **Not a chain client.** This SDK talks to walletd, which talks to a node.
  It never holds keys, never signs transactions, never derives addresses.
  If you want client-side signing, run walletd.
- Not a high-level wallet abstraction. Methods map 1:1 to the wire grammar;
  build helpers on top as your application needs them.

## Token discovery

Three ways to construct a client:

```python
# 1. Explicit (everywhere)
Client("http://127.0.0.1:8080", "your-token")

# 2. From env vars (deployed backends)
#    WALLETD_URL=http://walletd.internal:8080
#    WALLETD_AUTH_TOKEN=...
Client.from_env()

# 3. From a local walletd datadir (dev / colocated)
Client.from_datadir()      # reads ~/.exfer-walletd/token
```

If walletd is configured with split scopes
(`WALLETD_AUTH_TOKEN_READ` + `WALLETD_AUTH_TOKEN_SPEND`), construct one
`Client` per scope. The SDK doesn't model scopes in its types — walletd
enforces them, and a read-only token calling `transfer` raises
`AuthenticationError`.

## Errors

Every documented walletd error code maps to a typed exception:

```python
from exfer_walletd import (
    AuthenticationError,      # -32001
    WalletNotFoundError,      # -32010
    UpstreamError,            # -32020 — walletd's upstream node is unreachable
    TxAuthError,              # -32030 — UTXO authentication failed
    InsufficientBalanceError, # -32031 — wallet can't cover amount+fee
    InvalidParamsError,       # -32602
    TransportError,           # walletd itself unreachable / non-JSON body
)
```

`InsufficientBalanceError.in_flight_reserved` is `True` when the shortfall
comes from UTXOs reserved by other pending transfers from the same walletd —
retry after they confirm.

## Status

`0.1.0` — alpha. Tested against `exfer-walletd >= 0.4.3`.

MIT licensed.
