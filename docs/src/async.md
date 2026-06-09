# Async usage

`AsyncClient` mirrors `Client` method-for-method on top of
[`httpx.AsyncClient`](https://www.python-httpx.org/async/). Use it from
FastAPI, aiohttp, or any other asyncio-based backend.

## Example

```python
from exfer_walletd import AsyncClient

async def main() -> None:
    async with AsyncClient.from_datadir() as c:
        assert await c.healthz()
        addr = (await c.generate_address())["address"]  # → {address, pubkey, index}
        bal  = await c.get_balance(addr)       # → int
        print(addr, bal)

import asyncio
asyncio.run(main())
```

## FastAPI

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from exfer_walletd import AsyncClient

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.walletd = AsyncClient.from_env()
    try:
        yield
    finally:
        await app.state.walletd.aclose()

app = FastAPI(lifespan=lifespan)

@app.get("/balance/{addr}")
async def balance(addr: str) -> dict[str, int]:
    return {"balance": await app.state.walletd.get_balance(addr)}
```

A single `AsyncClient` instance is reusable across all requests — it
owns an underlying connection pool, and httpx is concurrency-safe.

## Differences from `Client`

There are exactly two:

- Every RPC method is `async def` and must be `await`ed.
- Lifecycle is `async with AsyncClient(...)` / `await c.aclose()`
  instead of `with Client(...)` / `c.close()`.

Everything else — parameter shapes, return types, the exception
hierarchy — is identical. The two clients share `_transport.py` so
they can't drift on the wire.

## Concurrency

Calls multiplex over the underlying connection pool. Use the standard
asyncio primitives:

```python
import asyncio

async with AsyncClient.from_env() as c:
    balances = await asyncio.gather(
        c.get_balance(addr1),
        c.get_balance(addr2),
        c.get_balance(addr3),
    )
```

walletd handles concurrent reads cheaply. For concurrent **transfers**
from the *same* wallet, walletd's in-flight UTXO tracker serializes
them safely — see
[walletd's `transfer` docs](https://exfer-stack.github.io/exfer-walletd/rpc-reference.html#transfer)
for the details.
