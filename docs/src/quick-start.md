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

## TLS (production)

When walletd is run with `--tls` (walletd `>= 0.5.0`), point the SDK
at the `https://` URL and supply the SHA-256 fingerprint walletd
printed on first run:

```python
# Explicit
with Client(
    "https://walletd.internal:8443",
    token="…",
    fingerprint="sha256:b66953c47263ac0da8192676e4770f0f799563322985c57246a6fab1bf24aa86",
) as c:
    c.ping()

# From env vars (set WALLETD_FINGERPRINT alongside URL + TOKEN)
with Client.from_env() as c:
    c.ping()

# Colocated with walletd — reads cert.fingerprint automatically
with Client.from_datadir(url="https://127.0.0.1:8443") as c:
    c.ping()
```

The SDK pins the cert by hash rather than verifying it against the
CA chain — that's what makes the self-signed cert walletd generates
actually trustable. If the server presents the wrong cert, the SDK
raises [`FingerprintMismatchError`](./errors.md#fingerprintmismatcherror).

## Generate an address and watch its balance

```python
with Client.from_datadir() as c:
    addr = c.generate_address()      # → str
    print("deposit address:", addr)

    bal = c.get_balance(addr)        # → int (exfers)
    print("balance (exfers):", bal)
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

## Liveness probes

```python
with Client.from_datadir() as c:
    if not c.healthz():
        # walletd's HTTP layer is down (or unreachable)
        ...
    c.ping()
    # ping() returns None on success; raises on any failure.
    # Use it to verify the token is valid AND the JSON-RPC layer is up.
    # (healthz is unauthenticated and says nothing about token validity.)
```

## Handle errors

```python
from exfer_walletd import (
    Client,
    ExferError,                       # catch-all SDK error
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
    except ExferError as e:
        # blanket catch — `str(e)` includes the error code
        log.error(f"transfer failed: {e}")    # "[-32xxx] some message"
```

Every documented walletd error code is a typed exception — see
[Errors](./errors.md).

## Next

- [Async usage](./async.md) — if your backend is FastAPI / aiohttp / asyncio.
- [API reference](./api-reference.md) — every method, every parameter, every return shape.
