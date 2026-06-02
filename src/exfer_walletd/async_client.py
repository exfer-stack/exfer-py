"""Asynchronous JSON-RPC client for exfer-walletd.

Mirrors :class:`exfer_walletd.client.Client` method-for-method on top of
:class:`httpx.AsyncClient`. The envelope build / response decode logic
lives in :mod:`exfer_walletd._transport` and is shared with the sync
client, so the two cannot drift on the wire.
"""

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
    _FingerprintAsyncHTTPTransport,
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
    DetectSwapsResult,
    NameScriptResult,
    ResolveNameResult,
    SignMessageResult,
    VerifyMessageResult,
    Block,
    ContractStatsRow,
    FollowerStatus,
    HtlcClaimResult,
    HtlcListResult,
    HtlcLockResult,
    HtlcReclaimResult,
    HtlcRecord,
    HtlcRole,
    HtlcState,
    ListSettlementsResult,
    PaymentUri,
    SimulateHtlcLockResult,
    SimulateTransferResult,
    SpentByResult,
    Tip,
    Transaction,
    TransferResult,
    UtxosResult,
    WaitForPaymentResult,
    WaitForTxResult,
)

__all__ = ["AsyncClient"]

USER_AGENT = f"exfer-walletd-py/{__version__}"


class AsyncClient:
    """Asynchronous client for the exfer-walletd JSON-RPC API.

    Method surface and semantics mirror :class:`Client` exactly. Use
    ``async with AsyncClient(...)`` (or call :meth:`aclose`) so the
    underlying :class:`httpx.AsyncClient` is properly torn down.
    """

    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        fingerprint: str | None = None,
    ) -> None:
        if not token:
            raise ValueError("token must be a non-empty string")
        self._url = url.rstrip("/")
        self._token = token

        if fingerprint is not None and transport is not None:
            raise ValueError(
                "specify either fingerprint= or transport=, not both — "
                "the fingerprint param installs its own pinning transport"
            )
        if fingerprint is not None:
            if not self._url.startswith("https://"):
                raise ValueError(f"fingerprint= requires an https:// URL, got {self._url!r}")
            expected = parse_fingerprint(fingerprint)
            transport = _FingerprintAsyncHTTPTransport(expected)

        self._http = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": USER_AGENT},
        )
        self._ids = _IdCounter()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

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
    ) -> AsyncClient:
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
    ) -> AsyncClient:
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

    async def healthz(self) -> bool:
        """TCP+HTTP-only probe. Returns ``False`` on any failure."""
        try:
            resp = await self._http.get(f"{self._url}/healthz")
        except httpx.HTTPError:
            return False
        return resp.status_code == 200 and resp.text.startswith("ok")

    async def ping(self) -> None:
        """Authenticated round-trip. Raises on any failure."""
        await self._call("ping", None)

    # ------------------------------------------------------------------
    # Read scope
    # ------------------------------------------------------------------

    async def generate_address(self) -> str:
        result = await self._call("generate_address", None)
        if not isinstance(result, dict) or "address" not in result:
            raise RuntimeError(f"generate_address returned unexpected shape: {result!r}")
        return str(result["address"])

    async def list_addresses(self) -> list[str]:
        result = await self._call("list_addresses", None)
        if not isinstance(result, dict) or "addresses" not in result:
            raise RuntimeError(f"list_addresses returned unexpected shape: {result!r}")
        addresses = result["addresses"]
        if not isinstance(addresses, list):
            raise RuntimeError(f"list_addresses.addresses is not a list: {addresses!r}")
        return [str(a) for a in addresses]

    async def get_balance(self, address: str) -> int:
        result = await self._call("get_balance", {"address": address})
        if not isinstance(result, dict) or "balance" not in result:
            raise RuntimeError(f"get_balance returned unexpected shape: {result!r}")
        return int(result["balance"])

    async def get_address_utxos(self, address: str) -> UtxosResult:
        return cast(UtxosResult, await self._call("get_address_utxos", {"address": address}))

    async def get_script_utxos(self, script_hex: str) -> UtxosResult:
        return cast(UtxosResult, await self._call("get_script_utxos", {"script_hex": script_hex}))

    async def get_block_height(self) -> int:
        result = await self._call("get_block_height", None)
        if not isinstance(result, dict) or "height" not in result:
            raise RuntimeError(f"get_block_height returned unexpected shape: {result!r}")
        return int(result["height"])

    async def get_tip(self) -> Tip:
        result = await self._call("get_block_height", None)
        if not isinstance(result, dict) or "height" not in result or "block_id" not in result:
            raise RuntimeError(f"get_tip returned unexpected shape: {result!r}")
        return Tip(int(result["height"]), str(result["block_id"]))

    async def get_block_by_height(self, height: int) -> Block:
        return cast(Block, await self._call("get_block", {"height": height}))

    async def get_block_by_hash(self, block_hash: str) -> Block:
        return cast(Block, await self._call("get_block", {"hash": block_hash}))

    async def get_transaction(self, tx_id: str) -> Transaction:
        return cast(Transaction, await self._call("get_transaction", {"hash": tx_id}))

    # ------------------------------------------------------------------
    # Spend scope
    # ------------------------------------------------------------------

    async def transfer(
        self,
        *,
        from_: str,
        to: str,
        amount: int,
        fee: int | None = None,
    ) -> TransferResult:
        params: dict[str, Any] = {"from": from_, "to": to, "amount": amount}
        if fee is not None:
            params["fee"] = fee
        return cast(TransferResult, await self._call("transfer", params))

    async def send_raw_transaction(self, tx_hex: str) -> str:
        result = await self._call("send_raw_transaction", {"tx_hex": tx_hex})
        if not isinstance(result, dict) or "tx_id" not in result:
            raise RuntimeError(f"send_raw_transaction returned unexpected shape: {result!r}")
        return str(result["tx_id"])

    async def htlc_lock(
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
        return cast(
            HtlcLockResult,
            await self._call("htlc_lock", _htlc_lock_params(
                from_, receiver, hash_lock, timeout, amount, fee, fee_rate, max_fee,
            )),
        )

    async def htlc_claim(
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
        return cast(HtlcClaimResult, await self._call("htlc_claim", params))

    async def htlc_reclaim(
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
        return cast(HtlcReclaimResult, await self._call("htlc_reclaim", params))

    # ------------------------------------------------------------------
    # Dry-run simulation
    # ------------------------------------------------------------------

    async def simulate_transfer(
        self,
        *,
        from_: str,
        outputs: list[Mapping[str, Any]],
        fee: int | None = None,
        fee_rate: int | None = None,
        max_fee: int | None = None,
    ) -> SimulateTransferResult:
        return cast(
            SimulateTransferResult,
            await self._call("simulate_transfer", _simulate_transfer_params(
                from_, outputs, fee, fee_rate, max_fee,
            )),
        )

    async def simulate_htlc_lock(
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
        return cast(
            SimulateHtlcLockResult,
            await self._call("simulate_htlc_lock", _htlc_lock_params(
                from_, receiver, hash_lock, timeout, amount, fee, fee_rate, max_fee,
            )),
        )

    # ------------------------------------------------------------------
    # Payment URI codec
    # ------------------------------------------------------------------

    async def payment_uri_encode(
        self,
        *,
        address: str,
        amount: int | None = None,
        memo: str | None = None,
        hash_lock: str | None = None,
        timeout: int | None = None,
        label: str | None = None,
    ) -> str:
        params = _payment_uri_params(address, amount, memo, hash_lock, timeout, label)
        result = await self._call("payment_uri_encode", params)
        if not isinstance(result, dict) or "uri" not in result:
            raise RuntimeError(f"payment_uri_encode returned unexpected shape: {result!r}")
        return str(result["uri"])

    async def payment_uri_decode(self, uri: str) -> PaymentUri:
        return cast(PaymentUri, await self._call("payment_uri_decode", {"uri": uri}))

    # ------------------------------------------------------------------
    # HTLC observability
    # ------------------------------------------------------------------

    async def htlc_status(self, lock_tx_id: str, output_index: int = 0) -> HtlcRecord:
        params = {"lock_tx_id": lock_tx_id, "output_index": output_index}
        return cast(HtlcRecord, await self._call("htlc_status", params))

    async def htlc_list(
        self,
        *,
        role: HtlcRole | None = None,
        state: HtlcState | list[HtlcState] | None = None,
        since_height: int | None = None,
        address: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> HtlcListResult:
        params = _htlc_list_params(role, state, since_height, address, limit, cursor)
        return cast(HtlcListResult, await self._call("htlc_list", params))

    async def htlc_forget(self, lock_tx_id: str, output_index: int = 0) -> bool:
        params = {"lock_tx_id": lock_tx_id, "output_index": output_index}
        result = await self._call("htlc_forget", params)
        if not isinstance(result, dict) or "removed" not in result:
            raise RuntimeError(f"htlc_forget returned unexpected shape: {result!r}")
        return bool(result["removed"])

    async def get_follower_status(self) -> FollowerStatus:
        return cast(FollowerStatus, await self._call("get_follower_status", None))

    async def wait_for_tx(
        self,
        tx_id: str,
        *,
        min_confirmations: int = 1,
        timeout_secs: int = 60,
    ) -> WaitForTxResult:
        params = {
            "tx_id": tx_id,
            "min_confirmations": min_confirmations,
            "timeout_secs": timeout_secs,
        }
        return cast(WaitForTxResult, await self._call("wait_for_tx", params))

    async def wait_for_payment(
        self,
        address: str,
        *,
        min_amount: int = 1,
        timeout_secs: int = 60,
    ) -> WaitForPaymentResult:
        """Block until a new credit of at least ``min_amount`` reaches ``address``.

        Returns as soon as the payment is *seen* in the node's mempool (0
        confirmations) — sub-second when the node's SSE push is connected.
        A receipt/liveness signal, not settlement finality; pair with
        :meth:`wait_for_tx` for a confirmation depth. On timeout the result
        has ``received`` False and ``timed_out`` True.
        """
        params = {
            "address": address,
            "min_amount": min_amount,
            "timeout_secs": timeout_secs,
        }
        return cast(
            WaitForPaymentResult, await self._call("wait_for_payment", params)
        )

    # ------------------------------------------------------------------
    # Indexer-delegated
    # ------------------------------------------------------------------

    async def list_settlements(
        self,
        address: str,
        *,
        contract_hash: str | None = None,
        since_height: int | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> ListSettlementsResult:
        params = _addr_paginated_params(address, contract_hash, since_height, limit, cursor)
        return cast(ListSettlementsResult, await self._call("list_settlements", params))

    async def contract_stats(
        self,
        address: str,
        *,
        contract_hash: str | None = None,
    ) -> list[ContractStatsRow]:
        params: dict[str, Any] = {"address": address}
        if contract_hash is not None:
            params["contract_hash"] = contract_hash
        result = await self._call("contract_stats", params)
        if not isinstance(result, dict) or "stats" not in result:
            raise RuntimeError(f"contract_stats returned unexpected shape: {result!r}")
        return cast(list[ContractStatsRow], result["stats"])

    async def get_address_history(
        self,
        address: str,
        *,
        since_height: int | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AddressHistoryResult:
        params = _addr_paginated_params(address, None, since_height, limit, cursor)
        return cast(AddressHistoryResult, await self._call("get_address_history", params))

    async def sign_message(self, address: str, message: str) -> SignMessageResult:
        """Sign an arbitrary UTF-8 message with ``address``'s key
        (domain-separated under EXFER-MSG). Proof of key control for
        off-chain challenge-response / agent identity."""
        return cast(
            SignMessageResult,
            await self._call("sign_message", {"address": address, "message": message}),
        )

    async def verify_message(
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
        return cast(VerifyMessageResult, await self._call("verify_message", params))

    async def name_script(self, name: str) -> NameScriptResult:
        """Derive the burn-script a name maps to (pure, no upstream call)."""
        return cast(NameScriptResult, await self._call("name_script", {"name": name}))

    async def resolve_name(self, name: str) -> ResolveNameResult:
        """Resolve a name to the address it points to (highest-cumulative-burn
        owner's declared target, else the owner). Requires an indexer-backed
        walletd."""
        return cast(ResolveNameResult, await self._call("resolve_name", {"name": name}))

    async def name_claim(
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
        return cast("dict[str, Any]", await self._call("name_claim", params))

    async def get_attestation_edges(
        self,
        address: str,
        *,
        contract_hash: str | None = None,
    ) -> AttestationEdgesResult:
        """Per-counterparty reputation edges for ``address`` — how many
        contracts ran with each counterparty and how they resolved
        (succeeded / refunded). The on-chain trust signal an agent can
        check before transacting. Requires an indexer-backed walletd."""
        params: dict[str, Any] = {"address": address}
        if contract_hash is not None:
            params["contract_hash"] = contract_hash
        return cast(AttestationEdgesResult, await self._call("get_attestation_edges", params))

    async def detect_in_chain_swaps(
        self,
        *,
        hash_lock: str | None = None,
        limit: int | None = None,
    ) -> DetectSwapsResult:
        """Groups of HTLCs sharing a hash_lock — the on-chain fingerprint
        of atomic swaps. Requires an indexer-backed walletd."""
        params: dict[str, Any] = {}
        if hash_lock is not None:
            params["hash_lock"] = hash_lock
        if limit is not None:
            params["limit"] = limit
        return cast(DetectSwapsResult, await self._call("detect_in_chain_swaps", params))

    async def htlc_lookup_by_hashlock(self, hash_lock: str) -> list[HtlcRecord]:
        result = await self._call("htlc_lookup_by_hashlock", {"hash_lock": hash_lock})
        if not isinstance(result, dict) or "htlcs" not in result:
            raise RuntimeError(f"htlc_lookup_by_hashlock returned unexpected shape: {result!r}")
        return cast(list[HtlcRecord], result["htlcs"])

    async def get_output_spent_by(self, tx_id: str, output_index: int) -> SpentByResult:
        params = {"tx_id": tx_id, "output_index": output_index}
        return cast(SpentByResult, await self._call("get_output_spent_by", params))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _call(self, method: str, params: Mapping[str, Any] | None) -> Any:
        envelope = build_envelope(method, params, self._ids.next())
        try:
            resp = await self._http.post(
                f"{self._url}/",
                json=envelope,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.HTTPError as exc:
            raise wrap_httpx_error(exc) from exc
        return decode_response(resp)
