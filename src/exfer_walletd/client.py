"""Synchronous JSON-RPC client for exfer-walletd."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Any, cast

import httpx

from ._params import (
    _addr_paginated_params,
    _htlc_list_params,
    _htlc_lock_params,
    _payment_uri_params,
    _simulate_transfer_params,
)
from ._transport import (
    _FingerprintHTTPTransport,
    _IdCounter,
    build_envelope,
    decode_response,
    parse_fingerprint,
    wrap_httpx_error,
)
from ._version import __version__
from .types import (
    AddressHistoryResult,
    AttestationEdgesResult,
    Block,
    ContractStatsRow,
    DetectSwapsResult,
    FollowerStatus,
    HtlcClaimResult,
    HtlcListResult,
    HtlcLockResult,
    HtlcReclaimResult,
    HtlcRecord,
    HtlcRole,
    HtlcState,
    ListSettlementsResult,
    NameScriptResult,
    PaymentUri,
    ResolveNameResult,
    SignMessageResult,
    SimulateHtlcLockResult,
    SimulateTransferResult,
    SpentByResult,
    Tip,
    Transaction,
    TransferResult,
    UtxosResult,
    VerifyMessageResult,
    WaitForPaymentResult,
    WaitForTxResult,
)

__all__ = ["Client"]

USER_AGENT = f"exfer-walletd-py/{__version__}"


class Client:
    """Synchronous client for the exfer-walletd JSON-RPC API.

    Every JSON-RPC method is exposed as an instance method. Common
    single-value methods return bare values (``int``, ``str``); methods
    whose response carries multiple useful fields return
    :mod:`exfer_walletd.types` ``TypedDict`` instances or NamedTuples.
    Errors raise from the :mod:`exfer_walletd.errors` hierarchy
    (catch :class:`~exfer_walletd.ExferError` for "anything went wrong").

    The client owns an :class:`httpx.Client` for connection pooling and
    should be closed (use as a context manager or call :meth:`close`).

    Example::

        with Client("http://127.0.0.1:7448", token) as c:
            addr = c.generate_address()           # → str
            bal  = c.get_balance(addr)            # → int
            print(addr, bal)
    """

    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        fingerprint: str | None = None,
    ) -> None:
        if not token:
            raise ValueError("token must be a non-empty string")
        self._url = url.rstrip("/")
        self._token = token

        # `fingerprint=` and `transport=` are mutually exclusive: the former
        # wires up our pinning transport, so handing in a custom one would
        # silently bypass verification.
        if fingerprint is not None and transport is not None:
            raise ValueError(
                "specify either fingerprint= or transport=, not both — "
                "the fingerprint param installs its own pinning transport"
            )
        if fingerprint is not None:
            if not self._url.startswith("https://"):
                raise ValueError(f"fingerprint= requires an https:// URL, got {self._url!r}")
            expected = parse_fingerprint(fingerprint)
            transport = _FingerprintHTTPTransport(expected)

        self._http = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": USER_AGENT},
        )
        self._ids = _IdCounter()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Alternate constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        *,
        url_env: str = "WALLETD_URL",
        token_env: str = "WALLETD_AUTH_TOKEN",
        fingerprint_env: str = "WALLETD_FINGERPRINT",
        **kwargs: Any,
    ) -> Client:
        """Read ``url``, ``token``, and optionally ``fingerprint`` from env.

        Raises :class:`RuntimeError` if ``url`` or ``token`` are missing —
        explicit failure is better than silently falling back to a default
        that wouldn't be what a deployed backend wants. ``fingerprint`` is
        optional; if set and the URL is https, the SDK pins the TLS cert.
        """
        url = os.environ.get(url_env)
        token = os.environ.get(token_env)
        fingerprint = os.environ.get(fingerprint_env)
        if not url:
            raise RuntimeError(f"{url_env} is not set")
        if not token:
            raise RuntimeError(f"{token_env} is not set")
        if fingerprint:
            kwargs.setdefault("fingerprint", fingerprint)
        return cls(url, token, **kwargs)

    @classmethod
    def from_datadir(
        cls,
        *,
        url: str = "http://127.0.0.1:7448",
        datadir: str = "~/.exfer-walletd",
        **kwargs: Any,
    ) -> Client:
        """Read the bearer token (and TLS fingerprint when https) from walletd's datadir.

        Ergonomic for "I'm running walletd locally on this host." On a fresh
        walletd install the token file is created automatically on first
        run with permissions ``0600``; if walletd was started with ``--tls``
        it also writes ``cert.fingerprint`` alongside, which is consumed
        here whenever ``url`` is https.
        """
        datadir_path = Path(datadir).expanduser()
        token_path = datadir_path / "token"
        try:
            token = token_path.read_text().strip()
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"walletd token file not found at {token_path} — is walletd running on this host?"
            ) from exc
        if not token:
            raise RuntimeError(f"walletd token file at {token_path} is empty")

        if url.startswith("https://") and "fingerprint" not in kwargs:
            fingerprint_path = datadir_path / "cert.fingerprint"
            try:
                fingerprint = fingerprint_path.read_text().strip()
            except FileNotFoundError as exc:
                raise FileNotFoundError(
                    f"walletd fingerprint file not found at {fingerprint_path} — "
                    f"is walletd running with --tls?"
                ) from exc
            if not fingerprint:
                raise RuntimeError(f"walletd fingerprint file at {fingerprint_path} is empty")
            kwargs["fingerprint"] = fingerprint

        return cls(url, token, **kwargs)

    # ------------------------------------------------------------------
    # Liveness
    # ------------------------------------------------------------------

    def healthz(self) -> bool:
        """Probe ``GET /healthz`` — TCP+HTTP only, no auth, no RPC.

        Returns ``True`` iff walletd answered ``200 OK`` with body ``ok``.
        Returns ``False`` on any HTTP or transport failure (rather than
        raising) so this method drops cleanly into liveness loops.

        Caveat: a green ``healthz`` says nothing about whether your token
        is valid or whether the upstream node is reachable. Use
        :meth:`ping` for an authenticated round-trip through the
        JSON-RPC layer.
        """
        try:
            resp = self._http.get(f"{self._url}/healthz")
        except httpx.HTTPError:
            return False
        return resp.status_code == 200 and resp.text.startswith("ok")

    def ping(self) -> None:
        """Authenticated JSON-RPC round-trip. Raises on any failure.

        Use to verify the token is valid and the JSON-RPC layer is
        responsive. Returns nothing — success is "didn't raise".
        """
        self._call("ping", None)

    # ------------------------------------------------------------------
    # Read scope
    # ------------------------------------------------------------------

    def generate_address(self) -> str:
        """Create a new managed address. Returns the address (hex)."""
        result = self._call("generate_address", None)
        if not isinstance(result, dict) or "address" not in result:
            raise RuntimeError(f"generate_address returned unexpected shape: {result!r}")
        return str(result["address"])

    def list_addresses(self) -> list[str]:
        """Every address walletd holds a key for, sorted ascending."""
        result = self._call("list_addresses", None)
        if not isinstance(result, dict) or "addresses" not in result:
            raise RuntimeError(f"list_addresses returned unexpected shape: {result!r}")
        addresses = result["addresses"]
        if not isinstance(addresses, list):
            raise RuntimeError(f"list_addresses.addresses is not a list: {addresses!r}")
        return [str(a) for a in addresses]

    def get_balance(self, address: str) -> int:
        """Confirmed balance for ``address``, in exfers."""
        result = self._call("get_balance", {"address": address})
        if not isinstance(result, dict) or "balance" not in result:
            raise RuntimeError(f"get_balance returned unexpected shape: {result!r}")
        return int(result["balance"])

    def get_address_utxos(self, address: str) -> UtxosResult:
        """Confirmed UTXOs locked to ``address`` plus tip metadata."""
        return cast(UtxosResult, self._call("get_address_utxos", {"address": address}))

    def get_script_utxos(self, script_hex: str) -> UtxosResult:
        """Confirmed UTXOs matching a raw locking script."""
        return cast(UtxosResult, self._call("get_script_utxos", {"script_hex": script_hex}))

    def get_block_height(self) -> int:
        """Current chain tip height. For the (height, hash) pair, see :meth:`get_tip`."""
        result = self._call("get_block_height", None)
        if not isinstance(result, dict) or "height" not in result:
            raise RuntimeError(f"get_block_height returned unexpected shape: {result!r}")
        return int(result["height"])

    def get_tip(self) -> Tip:
        """Current chain tip as a ``Tip(height, block_id)`` NamedTuple."""
        result = self._call("get_block_height", None)
        if not isinstance(result, dict) or "height" not in result or "block_id" not in result:
            raise RuntimeError(f"get_tip returned unexpected shape: {result!r}")
        return Tip(int(result["height"]), str(result["block_id"]))

    def get_block_by_height(self, height: int) -> Block:
        """Fetch the block at ``height``."""
        return cast(Block, self._call("get_block", {"height": height}))

    def get_block_by_hash(self, block_hash: str) -> Block:
        """Fetch the block with the given hash."""
        return cast(Block, self._call("get_block", {"hash": block_hash}))

    def get_transaction(self, tx_id: str) -> Transaction:
        """Fetch a transaction by its ``tx_id``. Covers mempool + confirmed."""
        return cast(Transaction, self._call("get_transaction", {"hash": tx_id}))

    # ------------------------------------------------------------------
    # Spend scope
    # ------------------------------------------------------------------

    def transfer(
        self,
        *,
        from_: str,
        to: str,
        amount: int,
        fee: int | None = None,
    ) -> TransferResult:
        """Build, sign, and broadcast a payment from a managed wallet.

        ``from_`` (trailing underscore) maps to the wire field ``from``.
        ``amount`` and ``fee`` are integers in *exfers*. Omitting ``fee``
        lets walletd apply its default (100_000 exfers = 0.001 EXFER);
        pass an explicit integer to override.

        Raises :class:`~exfer_walletd.errors.WalletNotFoundError` if walletd
        doesn't hold the key for ``from_``, and
        :class:`~exfer_walletd.errors.InsufficientBalanceError` if the
        wallet can't cover ``amount + fee``.
        """
        params: dict[str, Any] = {"from": from_, "to": to, "amount": amount}
        if fee is not None:
            params["fee"] = fee
        return cast(TransferResult, self._call("transfer", params))

    def send_raw_transaction(self, tx_hex: str) -> str:
        """Broadcast a pre-signed transaction. Returns its ``tx_id``."""
        result = self._call("send_raw_transaction", {"tx_hex": tx_hex})
        if not isinstance(result, dict) or "tx_id" not in result:
            raise RuntimeError(f"send_raw_transaction returned unexpected shape: {result!r}")
        return str(result["tx_id"])

    def htlc_lock(
        self,
        *,
        from_: str,
        receiver: str,
        hash_lock: str,
        timeout: int,
        amount: int,
        fee: int | None = None,
        fee_rate: int | None = None,
        max_fee: int | None = None,
    ) -> HtlcLockResult:
        """Lock ``amount`` exfers from ``from_`` into a new HTLC output.

        ``receiver`` is the receiver's 32-byte pubkey (64 hex). ``timeout``
        is the absolute block height past which ``from_`` can reclaim.
        ``fee`` and ``fee_rate`` are mutually exclusive — omit both to
        let walletd pick its default fee rate.

        Returns a receipt with the lock transaction id and the
        ``output_index`` at which the HTLC output sits. Save those two
        values: every other HTLC operation needs them.
        """
        return cast(
            HtlcLockResult,
            self._call(
                "htlc_lock",
                _htlc_lock_params(
                    from_,
                    receiver,
                    hash_lock,
                    timeout,
                    amount,
                    fee,
                    fee_rate,
                    max_fee,
                ),
            ),
        )

    def htlc_claim(
        self,
        *,
        from_: str,
        lock_tx_id: str,
        preimage: str,
        sender: str,
        timeout: int,
        output_index: int = 0,
        fee: int | None = None,
    ) -> HtlcClaimResult:
        """Spend an HTLC via the hash arm by revealing ``preimage``.

        ``from_`` is the receiver wallet (it claims and receives the funds).
        ``preimage`` is hex (any length — the hash arm imposes no length
        bound). ``sender`` + ``timeout`` are needed to reconstruct the
        original locking script so walletd can build a valid spend.
        """
        params: dict[str, Any] = {
            "from": from_,
            "lock_tx_id": lock_tx_id,
            "output_index": output_index,
            "preimage": preimage,
            "sender": sender,
            "timeout": timeout,
        }
        if fee is not None:
            params["fee"] = fee
        return cast(HtlcClaimResult, self._call("htlc_claim", params))

    def htlc_reclaim(
        self,
        *,
        from_: str,
        lock_tx_id: str,
        receiver: str,
        hash_lock: str,
        timeout: int,
        output_index: int = 0,
        fee: int | None = None,
    ) -> HtlcReclaimResult:
        """Reclaim an expired HTLC via the timeout arm.

        ``from_`` is the original sender. Walletd checks the chain tip
        and refuses to broadcast if ``current_height <= timeout``.
        """
        params: dict[str, Any] = {
            "from": from_,
            "lock_tx_id": lock_tx_id,
            "output_index": output_index,
            "receiver": receiver,
            "hash_lock": hash_lock,
            "timeout": timeout,
        }
        if fee is not None:
            params["fee"] = fee
        return cast(HtlcReclaimResult, self._call("htlc_reclaim", params))

    # ------------------------------------------------------------------
    # Dry-run simulation (Read scope — never broadcasts)
    # ------------------------------------------------------------------

    def simulate_transfer(
        self,
        *,
        from_: str,
        outputs: list[Mapping[str, Any]],
        fee: int | None = None,
        fee_rate: int | None = None,
        max_fee: int | None = None,
    ) -> SimulateTransferResult:
        """Compute the exact ``(size, fee, fee_rate, ...)`` a real
        :meth:`transfer` would produce, without broadcasting or reserving
        UTXOs. Use this to prove a cost ceiling before committing to
        spend.

        ``outputs`` is a list of ``{"to": addr_hex, "amount": exfers}``.
        Up to 16 entries.
        """
        return cast(
            SimulateTransferResult,
            self._call(
                "simulate_transfer",
                _simulate_transfer_params(
                    from_,
                    outputs,
                    fee,
                    fee_rate,
                    max_fee,
                ),
            ),
        )

    def simulate_htlc_lock(
        self,
        *,
        from_: str,
        receiver: str,
        hash_lock: str,
        timeout: int,
        amount: int,
        fee: int | None = None,
        fee_rate: int | None = None,
        max_fee: int | None = None,
    ) -> SimulateHtlcLockResult:
        """Dry-run version of :meth:`htlc_lock`. No broadcast, no reservation."""
        return cast(
            SimulateHtlcLockResult,
            self._call(
                "simulate_htlc_lock",
                _htlc_lock_params(
                    from_,
                    receiver,
                    hash_lock,
                    timeout,
                    amount,
                    fee,
                    fee_rate,
                    max_fee,
                ),
            ),
        )

    # ------------------------------------------------------------------
    # Payment URI codec (pure, no I/O)
    # ------------------------------------------------------------------

    def payment_uri_encode(
        self,
        *,
        address: str,
        amount: int | None = None,
        memo: str | None = None,
        hash_lock: str | None = None,
        timeout: int | None = None,
        label: str | None = None,
    ) -> str:
        """Build a BIP21-style ``exfer:`` URI. Returns the URI string."""
        params = _payment_uri_params(address, amount, memo, hash_lock, timeout, label)
        result = self._call("payment_uri_encode", params)
        if not isinstance(result, dict) or "uri" not in result:
            raise RuntimeError(f"payment_uri_encode returned unexpected shape: {result!r}")
        return str(result["uri"])

    def payment_uri_decode(self, uri: str) -> PaymentUri:
        """Parse an ``exfer:`` URI back into its component fields."""
        return cast(PaymentUri, self._call("payment_uri_decode", {"uri": uri}))

    # ------------------------------------------------------------------
    # HTLC observability (walletd v1.9 — owned-key index)
    # ------------------------------------------------------------------

    def htlc_status(self, lock_tx_id: str, output_index: int = 0) -> HtlcRecord:
        """Return the current :class:`HtlcRecord` for a lock outpoint.

        Raises :class:`~exfer_walletd.errors.WalletdError` if walletd has
        no tracked HTLC at this outpoint. For arbitrary (non-owned)
        addresses, configure ``--indexer-rpc`` on walletd so this routes
        through the multi-tenant index.
        """
        params = {"lock_tx_id": lock_tx_id, "output_index": output_index}
        return cast(HtlcRecord, self._call("htlc_status", params))

    def htlc_list(
        self,
        *,
        role: HtlcRole | None = None,
        state: HtlcState | list[HtlcState] | None = None,
        since_height: int | None = None,
        address: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> HtlcListResult:
        """List HTLCs matching the filter, paginated.

        ``state`` accepts either a single :data:`~exfer_walletd.types.HtlcState`
        or a list of them; ``role`` filters on observer relationship.
        The returned dict contains ``htlcs`` (list of :class:`HtlcRecord`)
        and optionally ``next_cursor`` — pass it back to fetch the next
        page.
        """
        params = _htlc_list_params(role, state, since_height, address, limit, cursor)
        return cast(HtlcListResult, self._call("htlc_list", params))

    def htlc_forget(self, lock_tx_id: str, output_index: int = 0) -> bool:
        """Remove a settled HTLC entry from walletd's index.

        Only Claimed / Reclaimed entries may be forgotten; pending ones
        raise :class:`~exfer_walletd.errors.WalletdError`. Returns
        ``True`` if an entry was removed, ``False`` if nothing was
        tracked at this outpoint.
        """
        params = {"lock_tx_id": lock_tx_id, "output_index": output_index}
        result = self._call("htlc_forget", params)
        if not isinstance(result, dict) or "removed" not in result:
            raise RuntimeError(f"htlc_forget returned unexpected shape: {result!r}")
        return bool(result["removed"])

    def get_follower_status(self) -> FollowerStatus:
        """Snapshot of walletd's block-follower state — height, lag, counts."""
        return cast(FollowerStatus, self._call("get_follower_status", None))

    def wait_for_tx(
        self,
        tx_id: str,
        *,
        min_confirmations: int = 1,
        timeout_secs: int = 60,
    ) -> WaitForTxResult:
        """Block until ``tx_id`` has ``min_confirmations`` behind it.

        ``timeout_secs`` is clamped server-side at 600. On timeout raises
        :class:`~exfer_walletd.errors.WaitTimeoutError`; that is not a
        terminal failure of the tx itself — it may still confirm later.
        """
        params = {
            "tx_id": tx_id,
            "min_confirmations": min_confirmations,
            "timeout_secs": timeout_secs,
        }
        return cast(WaitForTxResult, self._call("wait_for_tx", params))

    def wait_for_payment(
        self,
        address: str,
        *,
        min_amount: int = 1,
        timeout_secs: int = 60,
    ) -> WaitForPaymentResult:
        """Block until a new credit of at least ``min_amount`` reaches ``address``.

        Returns as soon as the payment is *seen* in the node's mempool (0
        confirmations) — sub-second when the node's SSE push is connected.
        This is a receipt/liveness signal, not settlement finality; pair
        with :meth:`wait_for_tx` for a confirmation depth.

        ``timeout_secs`` is clamped server-side at 600. A quiet window is
        not an error: on timeout the result has ``received`` False and
        ``timed_out`` True, so you can simply call again.
        """
        params = {
            "address": address,
            "min_amount": min_amount,
            "timeout_secs": timeout_secs,
        }
        return cast(WaitForPaymentResult, self._call("wait_for_payment", params))

    # ------------------------------------------------------------------
    # Indexer-delegated (walletd v1.9.1 — multi-tenant queries)
    # ------------------------------------------------------------------

    def list_settlements(
        self,
        address: str,
        *,
        contract_hash: str | None = None,
        since_height: int | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> ListSettlementsResult:
        """History of settled HTLCs involving ``address``.

        Raises :class:`~exfer_walletd.errors.IndexerNotConfiguredError`
        if walletd was not started with ``--indexer-rpc``.
        """
        params = _addr_paginated_params(address, contract_hash, since_height, limit, cursor)
        return cast(ListSettlementsResult, self._call("list_settlements", params))

    def contract_stats(
        self,
        address: str,
        *,
        contract_hash: str | None = None,
    ) -> list[ContractStatsRow]:
        """Aggregate stats per contract type for ``address``.

        Without ``contract_hash``, returns one row per distinct contract
        the address has settled. With ``contract_hash``, returns a single
        row (or empty list) for that contract.
        """
        params: dict[str, Any] = {"address": address}
        if contract_hash is not None:
            params["contract_hash"] = contract_hash
        result = self._call("contract_stats", params)
        if not isinstance(result, dict) or "stats" not in result:
            raise RuntimeError(f"contract_stats returned unexpected shape: {result!r}")
        return cast(list[ContractStatsRow], result["stats"])

    def get_address_history(
        self,
        address: str,
        *,
        since_height: int | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AddressHistoryResult:
        """Activity timeline for ``address`` — every input + output it appears in."""
        params = _addr_paginated_params(address, None, since_height, limit, cursor)
        return cast(AddressHistoryResult, self._call("get_address_history", params))

    def sign_message(self, address: str, message: str) -> SignMessageResult:
        """Sign an arbitrary UTF-8 message with ``address``'s key
        (domain-separated under EXFER-MSG). Proof of key control for
        off-chain challenge-response / agent identity."""
        return cast(
            SignMessageResult,
            self._call("sign_message", {"address": address, "message": message}),
        )

    def verify_message(
        self,
        pubkey: str,
        signature: str,
        message: str,
        *,
        address: str | None = None,
    ) -> VerifyMessageResult:
        """Verify a message signature (pure crypto). If ``address`` is
        given, valid is true only if it also matches H(pubkey)."""
        params: dict[str, Any] = {"pubkey": pubkey, "signature": signature, "message": message}
        if address is not None:
            params["address"] = address
        return cast(VerifyMessageResult, self._call("verify_message", params))

    def name_script(self, name: str) -> NameScriptResult:
        """Derive the burn-script a name maps to (pure, no upstream call)."""
        return cast(NameScriptResult, self._call("name_script", {"name": name}))

    def resolve_name(self, name: str) -> ResolveNameResult:
        """Resolve a name to the address it points to (highest-cumulative-burn
        owner's declared target, else the owner). Requires an indexer-backed
        walletd."""
        return cast(ResolveNameResult, self._call("resolve_name", {"name": name}))

    def name_claim(
        self,
        name: str,
        *,
        from_: str,
        amount: int = 1000,
        target: str | None = None,
        fee: int | None = None,
    ) -> dict[str, Any]:
        """Claim (or out-bid for) a name by burning ``amount`` to its script.
        Ownership is the highest cumulative burn. ``target`` declares where
        the name points (default: ``from_``)."""
        params: dict[str, Any] = {"name": name, "from": from_, "amount": amount}
        if target is not None:
            params["target"] = target
        if fee is not None:
            params["fee"] = fee
        return cast("dict[str, Any]", self._call("name_claim", params))

    def get_attestation_edges(
        self,
        address: str,
        *,
        contract_hash: str | None = None,
    ) -> AttestationEdgesResult:
        """Per-counterparty reputation edges for ``address`` (contracts run,
        succeeded, refunded) — the on-chain trust signal to check before
        transacting with a counterparty. Requires an indexer-backed walletd."""
        params: dict[str, Any] = {"address": address}
        if contract_hash is not None:
            params["contract_hash"] = contract_hash
        return cast(AttestationEdgesResult, self._call("get_attestation_edges", params))

    def detect_in_chain_swaps(
        self,
        *,
        hash_lock: str | None = None,
        limit: int | None = None,
    ) -> DetectSwapsResult:
        """Groups of HTLCs sharing a hash_lock — atomic-swap fingerprint.
        Requires an indexer-backed walletd."""
        params: dict[str, Any] = {}
        if hash_lock is not None:
            params["hash_lock"] = hash_lock
        if limit is not None:
            params["limit"] = limit
        return cast(DetectSwapsResult, self._call("detect_in_chain_swaps", params))

    def htlc_lookup_by_hashlock(self, hash_lock: str) -> list[HtlcRecord]:
        """Every tracked HTLC committed to ``hash_lock`` — canonical
        atomic-swap fingerprint.
        """
        result = self._call("htlc_lookup_by_hashlock", {"hash_lock": hash_lock})
        if not isinstance(result, dict) or "htlcs" not in result:
            raise RuntimeError(f"htlc_lookup_by_hashlock returned unexpected shape: {result!r}")
        return cast(list[HtlcRecord], result["htlcs"])

    def get_output_spent_by(self, tx_id: str, output_index: int) -> SpentByResult:
        """Reverse-spend lookup: which tx spent ``(tx_id, output_index)``?

        The ``source`` field reveals where the answer came from
        (``"indexer-cache"``, ``"node"``, or ``"fallback-unknown-method"``
        for older nodes without the RPC). ``spent: false`` means
        nobody has spent it (yet) given the indexer's current view.
        """
        params = {"tx_id": tx_id, "output_index": output_index}
        return cast(SpentByResult, self._call("get_output_spent_by", params))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call(self, method: str, params: Mapping[str, Any] | None) -> Any:
        envelope = build_envelope(method, params, self._ids.next())
        try:
            resp = self._http.post(
                f"{self._url}/",
                json=envelope,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(exc) from exc
        return decode_response(resp)
