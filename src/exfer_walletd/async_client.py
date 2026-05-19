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

from ._transport import _IdCounter, build_envelope, decode_response, wrap_httpx_error
from ._version import __version__
from .types import (
    BalanceResult,
    Block,
    BlockHeightResult,
    GenerateAddressResult,
    PingResult,
    SendRawResult,
    Transaction,
    TransferResult,
    UtxosResult,
)

__all__ = ["AsyncClient"]


class AsyncClient:
    """Asynchronous client for the exfer-walletd JSON-RPC API.

    Method surface and semantics mirror :class:`Client` exactly. Use
    ``async with AsyncClient(...)`` (or call :meth:`aclose`) so the
    underlying :class:`httpx.AsyncClient` is properly torn down.

    Example::

        async with AsyncClient("http://127.0.0.1:8080", token) as c:
            print(await c.ping())
            addr = (await c.generate_address())["address"]
            print(await c.get_balance(addr))
    """

    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not token:
            raise ValueError("token must be a non-empty string")
        self._url = url.rstrip("/")
        self._token = token
        self._http = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": f"exfer-walletd-py/{__version__}"},
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
        **kwargs: Any,
    ) -> AsyncClient:
        """Read ``url`` and ``token`` from environment variables."""
        url = os.environ.get(url_env)
        token = os.environ.get(token_env)
        if not url:
            raise RuntimeError(f"{url_env} is not set")
        if not token:
            raise RuntimeError(f"{token_env} is not set")
        return cls(url, token, **kwargs)

    @classmethod
    def from_datadir(
        cls,
        *,
        url: str = "http://127.0.0.1:8080",
        datadir: str = "~/.exfer-walletd",
        **kwargs: Any,
    ) -> AsyncClient:
        """Read the bearer token from ``<datadir>/token`` (defaults to walletd's)."""
        token_path = Path(datadir).expanduser() / "token"
        try:
            token = token_path.read_text().strip()
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"walletd token file not found at {token_path} — is walletd running on this host?"
            ) from exc
        if not token:
            raise RuntimeError(f"walletd token file at {token_path} is empty")
        return cls(url, token, **kwargs)

    # ------------------------------------------------------------------
    # Liveness (unauthenticated)
    # ------------------------------------------------------------------

    async def healthz(self) -> bool:
        """Probe ``GET /healthz``. Returns ``False`` on any failure."""
        try:
            resp = await self._http.get(f"{self._url}/healthz")
        except httpx.HTTPError:
            return False
        return resp.status_code == 200 and resp.text.startswith("ok")

    # ------------------------------------------------------------------
    # Read scope
    # ------------------------------------------------------------------

    async def ping(self) -> PingResult:
        return cast(PingResult, await self._call("ping", None))

    async def generate_address(self) -> GenerateAddressResult:
        return cast(GenerateAddressResult, await self._call("generate_address", None))

    async def list_addresses(self) -> list[str]:
        result = await self._call("list_addresses", None)
        if not isinstance(result, dict) or "addresses" not in result:
            raise RuntimeError(f"list_addresses returned unexpected shape: {result!r}")
        addresses = result["addresses"]
        if not isinstance(addresses, list):
            raise RuntimeError(f"list_addresses.addresses is not a list: {addresses!r}")
        return [str(a) for a in addresses]

    async def get_balance(self, address: str) -> BalanceResult:
        return cast(BalanceResult, await self._call("get_balance", {"address": address}))

    async def get_address_utxos(self, address: str) -> UtxosResult:
        return cast(UtxosResult, await self._call("get_address_utxos", {"address": address}))

    async def get_script_utxos(self, script_hex: str) -> UtxosResult:
        return cast(UtxosResult, await self._call("get_script_utxos", {"script_hex": script_hex}))

    async def get_block_height(self) -> BlockHeightResult:
        return cast(BlockHeightResult, await self._call("get_block_height", None))

    async def get_block(
        self,
        *,
        height: int | None = None,
        hash: str | None = None,
    ) -> Block:
        if (height is None) == (hash is None):
            raise TypeError("get_block requires exactly one of `height` or `hash`")
        params: dict[str, Any] = {"height": height} if height is not None else {"hash": hash}
        return cast(Block, await self._call("get_block", params))

    async def get_transaction(self, hash: str) -> Transaction:
        return cast(Transaction, await self._call("get_transaction", {"hash": hash}))

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

    async def send_raw_transaction(self, tx_hex: str) -> SendRawResult:
        return cast(SendRawResult, await self._call("send_raw_transaction", {"tx_hex": tx_hex}))

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
