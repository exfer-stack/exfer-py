"""Synchronous JSON-RPC client for exfer-walletd."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Any, cast

import httpx

from ._transport import _IdCounter, build_envelope, decode_response, wrap_httpx_error
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

__all__ = ["Client"]


class Client:
    """Synchronous client for the exfer-walletd JSON-RPC API.

    All JSON-RPC methods are exposed as instance methods returning
    :mod:`exfer_walletd.types` ``TypedDict`` instances. Errors raise from
    the :mod:`exfer_walletd.errors` hierarchy.

    The client owns an :class:`httpx.Client` for connection pooling and
    should be closed (use as a context manager or call :meth:`close`).

    Example::

        with Client("http://127.0.0.1:8080", token) as c:
            print(c.ping())
            addr = c.generate_address()["address"]
            print(c.get_balance(addr))
    """

    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not token:
            raise ValueError("token must be a non-empty string")
        self._url = url.rstrip("/")
        self._token = token
        self._http = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": _user_agent()},
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
        **kwargs: Any,
    ) -> Client:
        """Read ``url`` and ``token`` from environment variables.

        Raises :class:`RuntimeError` if either is missing — explicit failure
        is better than silently falling back to a default that wouldn't be
        what a deployed backend wants.
        """
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
    ) -> Client:
        """Read the bearer token from a walletd datadir file (``<datadir>/token``).

        This is the ergonomic for "I'm running walletd locally on this host."
        On a fresh walletd install the token file is created automatically
        on first run with permissions ``0600``.
        """
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

    def healthz(self) -> bool:
        """Probe ``GET /healthz``. Returns ``True`` iff walletd is alive.

        No ``Authorization`` header is sent — the endpoint is unauthenticated
        and meant for container orchestrators. Returns ``False`` on any
        non-200 response or transport error rather than raising, so this
        method is suitable for liveness loops.
        """
        try:
            resp = self._http.get(f"{self._url}/healthz")
        except httpx.HTTPError:
            return False
        return resp.status_code == 200 and resp.text.startswith("ok")

    # ------------------------------------------------------------------
    # Read scope
    # ------------------------------------------------------------------

    def ping(self) -> PingResult:
        return cast(PingResult, self._call("ping", None))

    def generate_address(self) -> GenerateAddressResult:
        return cast(GenerateAddressResult, self._call("generate_address", None))

    def list_addresses(self) -> list[str]:
        """Enumerate every managed address. Sorted ascending.

        Returns a bare ``list[str]`` — the wire wrapper ``{"addresses": [...]}``
        carries no extra information, so unwrap at the SDK boundary.
        """
        result = self._call("list_addresses", None)
        if not isinstance(result, dict) or "addresses" not in result:
            raise RuntimeError(f"list_addresses returned unexpected shape: {result!r}")
        addresses = result["addresses"]
        if not isinstance(addresses, list):
            raise RuntimeError(f"list_addresses.addresses is not a list: {addresses!r}")
        return [str(a) for a in addresses]

    def get_balance(self, address: str) -> BalanceResult:
        return cast(BalanceResult, self._call("get_balance", {"address": address}))

    def get_address_utxos(self, address: str) -> UtxosResult:
        return cast(UtxosResult, self._call("get_address_utxos", {"address": address}))

    def get_script_utxos(self, script_hex: str) -> UtxosResult:
        return cast(UtxosResult, self._call("get_script_utxos", {"script_hex": script_hex}))

    def get_block_height(self) -> BlockHeightResult:
        return cast(BlockHeightResult, self._call("get_block_height", None))

    def get_block(
        self,
        *,
        height: int | None = None,
        hash: str | None = None,
    ) -> Block:
        """Fetch a block by height OR hash. Exactly one must be given."""
        if (height is None) == (hash is None):
            raise TypeError("get_block requires exactly one of `height` or `hash`")
        params: dict[str, Any] = {"height": height} if height is not None else {"hash": hash}
        return cast(Block, self._call("get_block", params))

    def get_transaction(self, hash: str) -> Transaction:
        return cast(Transaction, self._call("get_transaction", {"hash": hash}))

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
        ``amount`` and ``fee`` are integers in *exfers*.

        Raises :class:`~exfer_walletd.errors.WalletNotFoundError` if walletd
        doesn't hold the key for ``from_``, and
        :class:`~exfer_walletd.errors.InsufficientBalanceError` if the
        wallet can't cover ``amount + fee``.
        """
        params: dict[str, Any] = {"from": from_, "to": to, "amount": amount}
        if fee is not None:
            params["fee"] = fee
        return cast(TransferResult, self._call("transfer", params))

    def send_raw_transaction(self, tx_hex: str) -> SendRawResult:
        return cast(SendRawResult, self._call("send_raw_transaction", {"tx_hex": tx_hex}))

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


def _user_agent() -> str:
    from ._version import __version__

    return f"exfer-walletd-py/{__version__}"
