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
    Block,
    Tip,
    Transaction,
    TransferResult,
    UtxosResult,
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
