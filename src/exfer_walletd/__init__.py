"""Typed Python client for the exfer-walletd JSON-RPC API.

Quick start::

    from exfer_walletd import Client

    with Client("http://127.0.0.1:8080", token="...") as c:
        print(c.ping())
        addr = c.generate_address()["address"]
        print(c.get_balance(addr))

Every method maps 1:1 to a walletd JSON-RPC method; see the walletd RPC
reference at https://exfer-stack.github.io/exfer-walletd/rpc-reference.html.
"""

from __future__ import annotations

from ._version import __version__
from .async_client import AsyncClient
from .client import Client
from .errors import (
    AuthenticationError,
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
from .types import (
    BalanceResult,
    Block,
    BlockHeightResult,
    GenerateAddressResult,
    PingResult,
    SendRawResult,
    Transaction,
    TransferResult,
    Utxo,
    UtxosResult,
)

__all__ = [
    "AsyncClient",
    "AuthenticationError",
    "BalanceResult",
    "Block",
    "BlockHeightResult",
    "Client",
    "GenerateAddressResult",
    "InsufficientBalanceError",
    "InternalError",
    "InvalidParamsError",
    "MethodNotFoundError",
    "ParseError",
    # types
    "PingResult",
    "ProtocolError",
    "SendRawResult",
    "Transaction",
    "TransferResult",
    "TransportError",
    "TxAuthError",
    "UpstreamError",
    "Utxo",
    "UtxosResult",
    "WalletExistsError",
    "WalletNotFoundError",
    # errors
    "WalletdError",
    "__version__",
]
