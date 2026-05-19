# Changelog

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
