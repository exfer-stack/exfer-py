# Changelog

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
