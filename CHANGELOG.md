# Changelog

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
