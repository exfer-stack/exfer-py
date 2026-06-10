"""Typed Python client for the exfer-walletd JSON-RPC API.

Quick start::

    from exfer import Client

    with Client("http://127.0.0.1:7448", token="...") as c:
        res = c.generate_address()           # → {address, pubkey, index}
        print(c.get_balance(res["address"]))  # → int

Every method maps 1:1 to a walletd JSON-RPC method; see
https://exfer-stack.github.io/exfer-py/.

Result *types* live in :mod:`exfer.types` (``Block``,
``Transaction``, ``Tip``, …) — import from there if you want to
annotate variables; you don't need to touch them for normal use.
"""

from __future__ import annotations

from ._version import __version__
from .async_client import AsyncClient
from .client import Client
from .errors import (
    AuthenticationError,
    ExferError,
    FingerprintMismatchError,
    IndexerNotConfiguredError,
    InsufficientBalanceError,
    InternalError,
    InvalidParamsError,
    MethodNotFoundError,
    ParseError,
    ProtocolError,
    TransportError,
    TxAuthError,
    UpstreamError,
    WaitTimeoutError,
    WalletdError,
    WalletExistsError,
    WalletNotFoundError,
)
from .types import Tip

__all__ = [
    "AsyncClient",
    "AuthenticationError",
    "Client",
    "ExferError",
    "FingerprintMismatchError",
    "IndexerNotConfiguredError",
    "InsufficientBalanceError",
    "InternalError",
    "InvalidParamsError",
    "MethodNotFoundError",
    "ParseError",
    "ProtocolError",
    "Tip",
    "TransportError",
    "TxAuthError",
    "UpstreamError",
    "WaitTimeoutError",
    "WalletExistsError",
    "WalletNotFoundError",
    "WalletdError",
    "__version__",
]
