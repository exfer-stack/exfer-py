# FAQ

## Does the SDK ever hold private keys?

No. Walletd is the only component that ever sees a private key. The
SDK is a typed HTTP client and nothing more.

## Why not pydantic?

The wire payload *is* a `dict`. Wrapping it in a pydantic model would
add a runtime construction cost, a 5 MB transitive dependency, and a
forward-compat liability (strict-by-default models break when walletd
adds a new field). `TypedDict` gives full mypy / pyright coverage at
zero cost and forward-compats trivially.

If you specifically want a pydantic model, build it on top — pass the
SDK's dict into `MyModel.model_validate(result)`.

## Why is there no retry on `-32020`?

Walletd already retries upstream node failures with linear backoff
(default 4 attempts, 500 ms base — see walletd's `RetryPolicy`).
Layering another retry inside the SDK would multiply latency without
adding reliability.

If walletd *itself* is unreachable (you get `TransportError`, not
`UpstreamError`), retry at the caller — that's a separate failure
mode the SDK can't sensibly handle for you.

## Can I use one client for both read and spend?

Yes. The SDK doesn't model scopes — a single `Client` carries one
bearer token, and walletd enforces what that token can do. If your
token is read-only and you call `transfer`, you get
`AuthenticationError`.

If you want hard separation between deposit-watcher and
withdrawal-worker, construct two `Client` instances with two tokens
and let the type system make crossing the line obvious.

## How do I detect "wallet is empty" vs "wallet is busy"?

`InsufficientBalanceError.in_flight_reserved`:

```python
except InsufficientBalanceError as e:
    if e.in_flight_reserved:
        # transient — pending transfers will free UTXOs
        retry_later()
    else:
        # actually empty — fund the wallet
        alert()
```

## Why does `transfer` use `from_` instead of `from`?

`from` is a Python keyword and can't be used as a parameter name. The
SDK accepts `from_` (trailing underscore, a common Python convention)
and translates to the wire field `from` before sending.

## How do I run the integration tests?

The integration suite spawns a real walletd binary. Build walletd
first:

```bash
cd ../exfer-walletd
cargo build --release
cd ../exfer-py
pytest -m integration
```

Or point at a custom location:

```bash
WALLETD_BINARY=/usr/local/bin/exfer-walletd pytest -m integration
```

Tests skip cleanly if the binary isn't available.

## Which walletd versions are supported?

The SDK tracks walletd's current minor release. `v0.8.0` of the SDK is
tested against walletd `v1.9.1`; the CI integration job pins to that
exact tag. Any newer walletd should work — unknown error codes
gracefully fall through to bare `WalletdError`.

## Where do I report bugs?

[github.com/exfer-stack/exfer-py/issues](https://github.com/exfer-stack/exfer-py/issues).
For walletd-side issues (wire format, error semantics), report to
[exfer-walletd](https://github.com/exfer-stack/exfer-walletd/issues)
instead.
