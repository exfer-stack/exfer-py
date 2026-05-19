# Changelog

## 0.9.0

- **New: `Client.refresh_address(addr) -> BalanceEntry`** and
  `Client.refresh_addresses(list[str]) -> ListBalancesResult`
  (`AsyncClient` mirrors). Force a synchronous cache refresh —
  bypasses TTL, hits upstream, CAS-writes the L2 + L3 cache, returns
  the post-refresh row(s).

  Use when the app knows a specific event affected an address (user
  clicked check deposit, internal sweep completed, webhook fired
  from elsewhere). Per-call upstream failures (rate limit, transport
  error) surface in the row's `last_error` field — both methods
  return 200 with the row, not raise.

  Requires walletd v0.14.0+.

  ```python
  row = client.refresh_address("ab" * 32)
  print(row["balance"], row["stale"], row["last_error"])
  ```

- **Behavior context (walletd-side breaking change in v0.14.0)**: the
  `balanced` cache profile no longer auto-polls by default
  (`refresh_interval = 0`). Pre-v0.14.0 walletd users upgrading will
  find `list_balances` rows stuck at their last-known values until
  the app calls `refresh_address` / `refresh_addresses`, or until
  the operator opts back into auto-polling via
  `--cache-refresh-secs N`. See walletd's operations docs for the
  4N math that motivated the breaking change.

- `list_balances` docstrings now point at the new refresh methods
  as the right primitive for "I know X changed, give me a fresh
  value now."

## 0.8.0

- **New: `Client.list_balances()` / `AsyncClient.list_balances()`**.
  Returns every managed address with its cached balance + UTXO count
  + freshness envelope in a single RPC. The exchange dashboard pattern
  that used to cost `N+1` RPCs (1 × `list_addresses` + N ×
  `get_balance`) now costs **one**.

  ```python
  result = client.list_balances()
  result["tip"]["height"]                  # 589354
  result["addresses"][0]["balance"]        # 1500000 (or None if cold)
  result["addresses"][0]["stale"]          # False
  ```

  Requires walletd v0.13.0+ with `--cache-profile != off`. See the
  [`list_balances` RPC docs](https://exfer-stack.github.io/exfer-walletd/rpc-reference.html#list_balances)
  for the row shape and freshness semantics.

- **New types**: `BalanceEntry`, `ListBalancesResult` (TypedDicts).
  Importable from `exfer_walletd` for annotation.

- `list_addresses` docstring updated to point at `list_balances` when
  the caller wants per-address balance bundles.

- Caches on the walletd side are transparent to existing SDK callers
  — `get_balance` / `get_address_utxos` / `get_transaction` /
  `get_block` / `get_block_hash` wire shapes are unchanged, they just
  get cheaper.

## 0.7.0 — **breaking default**

- `Client.from_datadir()` / `AsyncClient.from_datadir()` default URL
  port flipped from `:8080` to `:7448`, matching walletd v0.7.0's new
  default `--bind`. If you set `--bind` on the walletd side, this is a
  no-op. If you relied on `:8080` defaults end-to-end, restart walletd
  with `--bind :8080` (or update your config to `:7448`).
- All examples in README + docs use `:7448`.

## 0.6.0

- **TLS pinning** for walletd's new `--tls` mode (walletd v0.5.0+).
  Construct with `Client(url="https://…", token="…",
  fingerprint="sha256:…")` and the SDK installs a custom transport that
  verifies the server's leaf cert by SHA-256 instead of CA chain.
  Mismatches raise `FingerprintMismatchError` (a `TransportError`
  subclass).
- `from_env()` gained `fingerprint_env="WALLETD_FINGERPRINT"` —
  optional; only used when set.
- `from_datadir()` auto-reads `<datadir>/cert.fingerprint` whenever
  `url` starts with `https://`. Plain http URLs ignore it entirely.
- `fingerprint=` and `transport=` are mutually exclusive (passing both
  raises `ValueError`); passing `fingerprint=` with an `http://` URL
  also raises (almost always a bug).
- Public re-exports: `FingerprintMismatchError`.

## 0.5.0 — **breaking**

API polish based on dogfooding. None of the bytes-on-the-wire changed;
this is purely SDK shape.

### Breaking changes

- **Single-value methods now return bare values**, not dicts:
  - `generate_address() -> str` (was `{"address": ..., "pubkey": ...}`;
    pubkey is dropped — open an issue if you need it back)
  - `get_balance(addr) -> int` (was `{"address": ..., "balance": ...}`)
  - `get_block_height() -> int` (was `{"height": ..., "block_id": ...}`)
  - `send_raw_transaction(tx_hex) -> str` (was `{"tx_id": ...}`)
- **`get_block(*, height|hash)` split into two methods**:
  - `get_block_by_height(height: int) -> Block`
  - `get_block_by_hash(block_hash: str) -> Block`
  - The keyword-variant raised `TypeError` at runtime when called wrong;
    splitting kills the runtime check and gives IDEs full signal.
- **`get_transaction(tx_id=...)`** — parameter renamed from `hash` (the
  builtin) to `tx_id` (the semantic name). Wire field stays `hash`.
- **`ping() -> None`** (was `{"ok": True}`). Success = "didn't raise".
- **`WalletdError.__str__`** now includes the code:
  `"[-32020] upstream node unreachable"`. `e.code` and `e.message`
  still exist as attributes.

### Additions

- **`ExferError`** — common ancestor of `WalletdError` and
  `TransportError`. Lets you `except ExferError` as a blanket SDK
  catch (the two operational branches stay distinct underneath).
- **`get_tip() -> Tip`** — `NamedTuple(height: int, block_id: str)`
  for the case where you want both pieces of the chain tip. Use
  `get_block_height()` when you only need the int.
- **`InsufficientBalanceError.in_flight_reserved`** now prefers the
  error envelope's `data` field over message-scraping, with the
  message-scrape as a fallback. Forward-compatible with a planned
  walletd change to surface this structurally.

### Internal

- `TypedDict`s no longer re-exported from `exfer_walletd` top-level —
  import from `exfer_walletd.types` if you want them. `Tip` stays
  top-level because it's the actual return type of a method.
- `User-Agent` version no longer late-imported inside a helper
  function.

## 0.4.0

- mdBook docs site (`docs/`) deployed to GitHub Pages on every push to
  main. Covers intro, install, quick-start, async usage, full API
  reference, errors table, and FAQ. Local preview: `mdbook serve docs`.

## 0.3.0

- `tests/integration/` spawns a real `exfer-walletd` binary in a temp
  datadir with `--node-rpc` pointed at a closed port. Round-trips
  `healthz`, `ping`, `generate_address`, `list_addresses`, plus auth
  and upstream-error rejection. Skipped automatically if the binary
  isn't built (`cargo build --release` in `../exfer-walletd`) or
  `WALLETD_BINARY` env var isn't set.
- New CI job `integration` checks out `exfer-stack/exfer-walletd@v0.4.3`,
  builds it, and runs the integration suite on `main` pushes.
- `InsufficientBalanceError.in_flight_reserved` now has a regression
  test that reconstructs walletd's exact format string from
  `src/error.rs::insufficient_balance_message` byte-for-byte — if
  walletd ever rewords the message, the test catches it before users
  hit a silently-wrong `False`.

## 0.2.0

- `AsyncClient` mirrors every method on `Client`, on top of
  `httpx.AsyncClient`. Sync and async share `_transport.py` so they
  can't drift on the wire.

## 0.1.0

Initial release.

- Sync `Client` covering every `exfer-walletd` JSON-RPC method:
  `ping`, `generate_address`, `list_addresses`, `get_balance`,
  `get_address_utxos`, `get_script_utxos`, `get_block_height`,
  `get_block`, `get_transaction`, `transfer`, `send_raw_transaction`.
- Unauthenticated `healthz()` for liveness probes.
- Typed exception hierarchy mapped 1:1 to walletd's documented
  JSON-RPC error codes.
- `TypedDict` return shapes for every result — zero runtime cost,
  full mypy/pyright coverage.
