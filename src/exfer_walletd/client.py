"""Synchronous JSON-RPC client for exfer-walletd."""

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
    Block,
    Tip,
    Transaction,
    TransferResult,
    UtxosResult,
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

        with Client("http://127.0.0.1:8080", token) as c:
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
    ) -> None:
        if not token:
            raise ValueError("token must be a non-empty string")
        self._url = url.rstrip("/")
        self._token = token
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

        Ergonomic for "I'm running walletd locally on this host." On a
        fresh walletd install the token file is created automatically on
        first run with permissions ``0600``.
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
