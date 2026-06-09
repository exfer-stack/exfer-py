# Changelog

## 0.9.0 — 2026-06-09

### Breaking — address methods now return full records

- `generate_address()` now returns a `GenerateAddressResult`
  (`{"address", "pubkey", "index"}`) instead of a bare `str`. The
  `pubkey` was previously dropped on the floor; it is the value to pass
  as `payee_pubkey` to `quote_issue`, so callers no longer have to abuse
  `sign_message` to recover it. Migrate `addr = c.generate_address()` →
  `addr = c.generate_address()["address"]`.
- `list_addresses()` now returns `list[AddressRecord]`
  (`{"address", "index"?, "label"?, "imported"?}`) instead of
  `list[str]`, preserving the keystore index and label/imported flag.
  Migrate `for a in c.list_addresses()` →
  `for rec in c.list_addresses(): a = rec["address"]`.

New `TypedDict`s `GenerateAddressResult` and `AddressRecord` in
`exfer_walletd.types`. Mirrored on both `Client` and `AsyncClient`.

### New methods

- `get_output_datum()` and `find_settlements_by_quote_id()` — the
  EXFER-QUOTE settlement read surface (indexer-delegated on walletd).
- `simulate_transfer()` gained an optional `datum` argument, so a
  settlement dry-run reflects the on-chain size of the datum it carries.

### Fixes

- `transfer()` now sends the `outputs` array walletd expects; the old
  flat `to`/`amount` shape was rejected by walletd.
- `wait_for_tx()` / `wait_for_payment()` extend the HTTP read timeout past
  the server-side wait, so a long confirmation wait no longer surfaces as a
  spurious "walletd unreachable" transport error.

## 0.8.0 — walletd v1.9 + v1.9.1 surface

Adds the seventeen JSON-RPC methods walletd grew over its v1.7 → v1.9.1
series. Purely additive — every method that worked in 0.7.0 still
returns the same shape, with the same default behaviour, against the
same default port.

### New methods (mirrored on `Client` + `AsyncClient`)

**HTLC spend trio (walletd v1.7+):**

- `htlc_lock(*, from_, receiver, hash_lock, timeout, amount, fee=, fee_rate=, max_fee=)`
- `htlc_claim(*, from_, lock_tx_id, preimage, sender, timeout, output_index=0, fee=)`
- `htlc_reclaim(*, from_, lock_tx_id, receiver, hash_lock, timeout, output_index=0, fee=)`

**Dry-run simulation (v1.9):**

- `simulate_transfer(*, from_, outputs, fee=, fee_rate=, max_fee=)`
- `simulate_htlc_lock(*, from_, receiver, hash_lock, timeout, amount, fee=, fee_rate=, max_fee=)`

Both methods compute the exact `(size, fee, fee_rate, ...)` a real call
would produce. No broadcast, no UTXO reservation. Lets an agent prove a
cost ceiling before committing to spend.

**Payment URI codec (v1.9, pure):**

- `payment_uri_encode(*, address, amount=, memo=, hash_lock=, timeout=, label=)`
- `payment_uri_decode(uri)`

BIP21-style `exfer:<address>?amount=...&memo=...` round trip.

**HTLC observability (v1.9, walletd's own index):**

- `htlc_status(lock_tx_id, output_index=0)`
- `htlc_list(*, role=, state=, since_height=, address=, limit=, cursor=)`
- `htlc_forget(lock_tx_id, output_index=0)`
- `get_follower_status()`
- `wait_for_tx(tx_id, *, min_confirmations=1, timeout_secs=60)`

`htlc_list` accepts either a single `HtlcState` or a list (untagged on
the wire, walletd handles both).

**Indexer-delegated (v1.9.1, multi-tenant queries):**

- `list_settlements(address, *, contract_hash=, since_height=, limit=, cursor=)`
- `contract_stats(address, *, contract_hash=)`
- `get_address_history(address, *, since_height=, limit=, cursor=)`
- `htlc_lookup_by_hashlock(hash_lock)`
- `get_output_spent_by(tx_id, output_index)`

These five methods need walletd to be running with `--indexer-rpc`
pointing at an `exfer-indexer` instance. When the flag isn't set the
SDK raises the new `IndexerNotConfiguredError`.

### New result shapes in `exfer_walletd.types`

`HtlcRecord` / `HtlcParams` / `HtlcClaimRecord` / `HtlcReclaimRecord` /
`HtlcState` (Literal) / `HtlcRole` (Literal) / `HtlcLockResult` /
`HtlcClaimResult` / `HtlcReclaimResult` / `SimulateTransferResult` /
`SimulateHtlcLockResult` / `FollowerStatus` / `WaitForTxResult` /
`PaymentUri` / `SettlementRecord` / `ListSettlementsResult` /
`ContractStatsRow` / `AddressHistoryRow` / `AddressHistoryResult` /
`HtlcListResult` / `SpentByResult`.

### New errors

- `WaitTimeoutError` (-32040) — `wait_for_tx` didn't see the depth in
  time. Not terminal; the tx may still confirm.
- `IndexerNotConfiguredError` (-32041) — caller hit an indexer-delegated
  method on a walletd without `--indexer-rpc` configured.

### Compatibility

- Default URL / port unchanged (`http://127.0.0.1:7448`).
- All pre-existing methods preserve their signatures + return types.
- No new required runtime dependencies (`httpx` only, same as 0.7.0).

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
