"""Typed Python client for the exfer-walletd JSON-RPC API.

Quick start::

    from exfer_walletd import Client

    with Client("http://127.0.0.1:8080", token="...") as c:
        addr = c.generate_address()          # → str
        print(c.get_balance(addr))           # → int

Every method maps 1:1 to a walletd JSON-RPC method; see
https://exfer-stack.github.io/exfer-py/.

Result *types* live in :mod:`exfer_walletd.types` (``Block``,
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
    InsufficientBalanceError,
    InternalError,
    InvalidParamsError,
    MethodNotFoundError,
    ParseError,
    ProtocolError,
    TransportError,
    TxAuthError,
    UpstreamError,
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
    "WalletExistsError",
    "WalletNotFoundError",
    "WalletdError",
    "__version__",
]
