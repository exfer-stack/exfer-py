# exfer-walletd (Python SDK)

A typed Python client for the
[exfer-walletd](https://github.com/exfer-stack/exfer-walletd) JSON-RPC
API.

```python
from exfer_walletd import Client

with Client("http://127.0.0.1:8080", token="...") as c:
    print(c.healthz())                # → True
    addr = c.generate_address()["address"]
    print(c.get_balance(addr))        # → {"address": "...", "balance": 0}
```

## What it is

- A thin wrapper over walletd's JSON-RPC. One Python method per RPC
  method, no abstraction in between.
- Both **sync** (`Client`) and **async** (`AsyncClient`) — same surface,
  shared wire layer.
- `TypedDict` return shapes. Zero runtime cost, full mypy / pyright
  coverage, no `pydantic` dependency forced on consumers.
- Stable error hierarchy mapped 1:1 to walletd's documented JSON-RPC
  error codes. Unknown codes fall through to bare `WalletdError` so
  future walletd releases don't break your code.

## What it isn't

- **Not a chain client.** This SDK talks to walletd; walletd talks to a
  node. The SDK never holds keys, never signs transactions, never
  derives addresses. If you need client-side signing, run walletd.
- Not a high-level wallet abstraction. Methods map 1:1 to the wire
  grammar; build helpers on top as your application needs them.

## Status

`0.3.0` — alpha. Tested against `exfer-walletd >= 0.4.3` (the
integration CI job pins to `v0.4.3`). API surface is stable; minor
versions may add methods as walletd does.

MIT licensed. Source:
[github.com/exfer-stack/exfer-py](https://github.com/exfer-stack/exfer-py).
