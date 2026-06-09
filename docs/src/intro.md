# exfer-walletd (Python SDK)

A typed Python client for the
[exfer-walletd](https://github.com/exfer-stack/exfer-walletd) JSON-RPC
API.

```python
from exfer_walletd import Client

with Client("http://127.0.0.1:7448", token="...") as c:
    assert c.healthz()                # → bool
    addr = c.generate_address()["address"]  # → {address, pubkey, index}
    bal  = c.get_balance(addr)        # → int (exfers)
    print(addr, bal)
```

## What it is

- A thin wrapper over walletd's JSON-RPC. One Python method per RPC
  method, no abstraction in between.
- Both **sync** (`Client`) and **async** (`AsyncClient`) — same surface,
  shared wire layer.
- Single-value endpoints (`get_balance`, `get_block_height`,
  `send_raw_transaction`, …) return bare Python values (`str`, `int`).
  Multi-field endpoints (`generate_address`, `list_addresses`, …) return
  `TypedDict`s.
- Stable error hierarchy mapped 1:1 to walletd's documented JSON-RPC
  error codes, all rooted at `ExferError`. Unknown codes fall through
  to bare `WalletdError` so future walletd releases don't break your
  code.

## What it isn't

- **Not a chain client.** This SDK talks to walletd; walletd talks to a
  node. The SDK never holds keys, never signs transactions, never
  derives addresses. If you need client-side signing, run walletd.
- Not a high-level wallet abstraction. Methods map 1:1 to the wire
  grammar; build helpers on top as your application needs them.

## Status

`0.5.0` — alpha. **Breaking changes from 0.4.x** (return shapes
unwrapped, `get_block` split, error code surfaced in `str()`); see the
[CHANGELOG](https://github.com/exfer-stack/exfer-py/blob/main/CHANGELOG.md).
Tested against `exfer-walletd >= 0.4.3`.

MIT licensed. Source:
[github.com/exfer-stack/exfer-py](https://github.com/exfer-stack/exfer-py).
