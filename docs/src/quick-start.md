# Quick start

This page assumes you have walletd running. If not, set it up first:
[walletd quick start](https://exfer-stack.github.io/exfer-walletd/quick-start.html).

## Construct a client

Three ways, depending on how your deployment hands out the token.

```python
from exfer_walletd import Client

# 1. Explicit (works everywhere)
c = Client("http://127.0.0.1:8080", "your-token")

# 2. From env vars (deployed backends)
#    Set WALLETD_URL + WALLETD_AUTH_TOKEN
c = Client.from_env()

# 3. From a local walletd datadir (dev / colocated services)
c = Client.from_datadir()       # reads ~/.exfer-walletd/token
```

`Client` is a context manager — use `with` so the underlying HTTP
connection pool gets torn down cleanly:

```python
with Client.from_datadir() as c:
    ...
```

## Generate an address and watch its balance

```python
with Client.from_datadir() as c:
    addr = c.generate_address()["address"]
    print("deposit address:", addr)

    bal = c.get_balance(addr)
    print("balance (exfers):", bal["balance"])
```

walletd persists the key file in its datadir under `wallets/<address>.key`
with mode `0600`. The SDK never sees the private key.

## Send a payment

```python
with Client.from_datadir() as c:
    r = c.transfer(
        from_="<your-managed-address>",
        to="<recipient-address>",
        amount=30_000_000,         # exfers; 1 EXFER = 100_000_000 exfers
        # fee defaults to 100_000 (= 0.001 EXFER) if omitted
    )
    print("submitted tx:", r["tx_id"])
```

> Note: `from_` (trailing underscore) is the parameter name because
> `from` is a Python keyword. The wire field walletd sees is plain
> `from`.

## Handle errors

```python
from exfer_walletd import (
    Client,
    InsufficientBalanceError,
    UpstreamError,
    WalletNotFoundError,
)

with Client.from_datadir() as c:
    try:
        c.transfer(from_=addr, to=other, amount=1_000_000_000)
    except InsufficientBalanceError as e:
        if e.in_flight_reserved:
            print("UTXOs reserved by pending transfers — retry shortly")
        else:
            print("wallet is empty; fund it first")
    except WalletNotFoundError:
        print("walletd doesn't hold the key for", addr)
    except UpstreamError as e:
        print("walletd's upstream node is unreachable:", e.message)
```

Every documented walletd error code is a typed exception — see
[Errors](./errors.md).

## Next

- [Async usage](./async.md) — if your backend is FastAPI / aiohttp / asyncio.
- [API reference](./api-reference.md) — every method, every parameter, every return shape.
