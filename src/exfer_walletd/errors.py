"""Exception hierarchy for the exfer-walletd SDK.

All SDK errors inherit from :class:`ExferError` so a blanket
``except ExferError`` catches everything — useful for top-level handlers.

Underneath, two operational classes:

- :class:`WalletdError` and its subclasses cover anything walletd
  returned as a JSON-RPC error envelope (including HTTP 400 for parse
  errors and HTTP 401 for auth).
- :class:`TransportError` covers failures *below* the JSON-RPC layer —
  walletd unreachable, connection reset, non-JSON body, etc.

Catch the narrow type when you have specific handling; ``ExferError``
when you just want "something went wrong with walletd".

If walletd ever ships a new error code the SDK doesn't know about, the
decoder falls through to bare :class:`WalletdError` with the raw
``code``/``message`` rather than swallowing it.
"""

from __future__ import annotations

__all__ = [
    "AuthenticationError",
    "ExferError",
    "InsufficientBalanceError",
    "InternalError",
    "InvalidParamsError",
    "MethodNotFoundError",
    "ParseError",
    "ProtocolError",
    "TransportError",
    "TxAuthError",
    "UpstreamError",
    "WalletExistsError",
    "WalletNotFoundError",
    "WalletdError",
    "error_for_code",
]


class ExferError(Exception):
    """Common base for every error raised by the SDK.

    Use this for "catch-all SDK errors" handlers; for finer-grained
    control catch :class:`WalletdError` (walletd answered with an error
    envelope) or :class:`TransportError` (walletd unreachable, etc.)
    individually.
    """


class WalletdError(ExferError):
    """A JSON-RPC error envelope returned by walletd."""

    code: int = 0

    def __init__(self, message: str, *, code: int | None = None, data: object = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.data = data

    def __str__(self) -> str:
        # Make logs / `print(e)` self-describing — the code is half the
        # debugging story and shouldn't require a separate `.code` lookup.
        return f"[{self.code}] {self.message}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code}, message={self.message!r})"


class TransportError(ExferError):
    """walletd unreachable, HTTP-level failure, or non-JSON body.

    Wraps the underlying :mod:`httpx` exception via ``__cause__``.
    """


class ProtocolError(WalletdError):
    """HTTP 200 but the envelope is missing both ``result`` and ``error``."""

    code = 0


# ---------------------------------------------------------------------------
# JSON-RPC standard codes
# ---------------------------------------------------------------------------


class ParseError(WalletdError):
    """-32700: walletd could not parse the request as JSON-RPC."""

    code = -32700


class MethodNotFoundError(WalletdError):
    """-32601: walletd does not know the requested method."""

    code = -32601


class InvalidParamsError(WalletdError):
    """-32602: params failed validation (bad hex, wrong length, …)."""

    code = -32602


class InternalError(WalletdError):
    """-32603: walletd hit an unexpected internal error."""

    code = -32603


# ---------------------------------------------------------------------------
# walletd-specific codes
# ---------------------------------------------------------------------------


class AuthenticationError(WalletdError):
    """-32001: bearer token missing, wrong, or has insufficient scope.

    Also raised when walletd returns HTTP 401, even if the JSON body
    couldn't be parsed (e.g. an upstream proxy stripped it).
    """

    code = -32001


class WalletNotFoundError(WalletdError):
    """-32010: ``from`` address has no key file on walletd's disk."""

    code = -32010


class WalletExistsError(WalletdError):
    """-32011: address collision on ``generate_address`` (effectively impossible)."""

    code = -32011


class UpstreamError(WalletdError):
    """-32020: upstream node unreachable or returned an RPC error.

    Walletd has already retried (default 4 attempts, linear backoff) before
    surfacing this. Don't retry blindly at the SDK layer; check ``message``
    to distinguish "node down" from e.g. "mempool rejected the tx".
    """

    code = -32020


class TxAuthError(WalletdError):
    """-32030: UTXO authentication or transaction construction failed.

    Almost always means the upstream node returned tx data that doesn't
    match the outpoint walletd asked about — the node is malicious or
    out of sync.
    """

    code = -32030


class InsufficientBalanceError(WalletdError):
    """-32031: wallet can't cover ``amount + fee``.

    :attr:`in_flight_reserved` is ``True`` iff the shortfall is partly
    because UTXOs are reserved by *other* pending transfers from this
    daemon. In that case retrying after a few seconds (once the pending
    transfers confirm) may succeed.

    The value comes from the error envelope's ``data`` field when walletd
    populates it; otherwise we fall back to a string match against the
    message. On parse miss, defaults to ``False`` — the safe choice so
    callers never blindly retry.
    """

    code = -32031

    in_flight_reserved: bool = False

    def __init__(self, message: str, *, code: int | None = None, data: object = None) -> None:
        super().__init__(message, code=code, data=data)
        self.in_flight_reserved = _detect_in_flight(message, data)


def _detect_in_flight(message: str, data: object) -> bool:
    """Prefer structured ``data`` over message scraping.

    walletd may eventually surface this as ``data["in_flight_reserved"]``
    (tracked upstream); until then we string-match against the canonical
    message format from ``exfer-walletd/src/error.rs::insufficient_balance_message``.
    """
    if isinstance(data, dict):
        flag = data.get("in_flight_reserved")
        if isinstance(flag, bool):
            return flag
    return "reserved by pending transfers" in message


# ---------------------------------------------------------------------------
# Code → exception mapping
# ---------------------------------------------------------------------------

_CODE_MAP: dict[int, type[WalletdError]] = {
    -32700: ParseError,
    -32601: MethodNotFoundError,
    -32602: InvalidParamsError,
    -32603: InternalError,
    -32001: AuthenticationError,
    -32010: WalletNotFoundError,
    -32011: WalletExistsError,
    -32020: UpstreamError,
    -32030: TxAuthError,
    -32031: InsufficientBalanceError,
}


def error_for_code(code: int, message: str, data: object = None) -> WalletdError:
    """Construct the right exception for a walletd JSON-RPC error code.

    Unknown codes fall through to bare :class:`WalletdError` so callers
    can still branch on ``.code``.
    """
    cls = _CODE_MAP.get(code, WalletdError)
    return cls(message, code=code, data=data)
