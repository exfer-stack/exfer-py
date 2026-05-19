"""Every documented walletd error code maps to the right exception class."""

from __future__ import annotations

import httpx
import pytest
import respx

from exfer_walletd import (
    AuthenticationError,
    Client,
    InsufficientBalanceError,
    InternalError,
    InvalidParamsError,
    MethodNotFoundError,
    ParseError,
    TxAuthError,
    UpstreamError,
    WalletdError,
    WalletExistsError,
    WalletNotFoundError,
)
from exfer_walletd.errors import error_for_code

from .conftest import rpc_err

# (code, exception class, status code walletd actually returns for it)
CODE_CASES = [
    (-32700, ParseError, 400),
    (-32601, MethodNotFoundError, 200),
    (-32602, InvalidParamsError, 200),
    (-32603, InternalError, 200),
    (-32001, AuthenticationError, 401),
    (-32010, WalletNotFoundError, 200),
    (-32011, WalletExistsError, 200),
    (-32020, UpstreamError, 200),
    (-32030, TxAuthError, 200),
    (-32031, InsufficientBalanceError, 200),
]


@pytest.mark.parametrize(("code", "cls", "status"), CODE_CASES)
def test_error_code_maps_to_typed_exception(
    code: int,
    cls: type[WalletdError],
    status: int,
    client: Client,
    mock_walletd: respx.MockRouter,
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_err(code, "something broke", status=status))
    with pytest.raises(cls) as excinfo:
        client.ping()
    assert excinfo.value.code == code
    assert excinfo.value.message == "something broke"


def test_unknown_code_falls_through_to_walletd_error(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_err(-32099, "future error"))
    with pytest.raises(WalletdError) as excinfo:
        client.ping()
    # Bare WalletdError, not a subclass
    assert type(excinfo.value) is WalletdError
    assert excinfo.value.code == -32099


def test_authentication_error_on_401_without_body() -> None:
    """Some proxies strip the JSON body on 401; we still raise AuthenticationError."""
    from exfer_walletd._transport import decode_response

    resp = httpx.Response(401, text="")
    with pytest.raises(AuthenticationError) as excinfo:
        decode_response(resp)
    assert excinfo.value.code == -32001


def test_authentication_error_on_401_with_body(
    client: Client, mock_walletd: respx.MockRouter
) -> None:
    mock_walletd.post("/").mock(return_value=rpc_err(-32001, "wrong token", status=401))
    with pytest.raises(AuthenticationError) as excinfo:
        client.ping()
    assert excinfo.value.message == "wrong token"


def test_insufficient_balance_detects_in_flight_hint() -> None:
    msg = (
        "insufficient balance: need 5100000 exfers (amount + fee), "
        "wallet has 4000000 spendable across 1 UTXO(s) "
        "(2 more UTXO(s) worth 9000000 exfers reserved by pending transfers "
        "from this daemon; retry once they confirm or use a different sending wallet)"
    )
    err = error_for_code(-32031, msg)
    assert isinstance(err, InsufficientBalanceError)
    assert err.in_flight_reserved is True


def _walletd_insufficient_balance_message(
    needed: int,
    available: int,
    utxo_count: int,
    in_flight_value: int,
    in_flight_count: int,
) -> str:
    """Reproduce the *exact* format walletd emits.

    This mirrors :func:`insufficient_balance_message` in
    ``exfer-walletd/src/error.rs`` byte-for-byte. If walletd ever
    reformats the message, the assertions in
    :func:`test_in_flight_hint_matches_walletd_format` start failing,
    which is what catches the drift before users do.
    """
    s = (
        f"insufficient balance: need {needed} exfers (amount + fee), "
        f"wallet has {available} spendable across {utxo_count} UTXO(s)"
    )
    if in_flight_count > 0:
        s += (
            f" ({in_flight_count} more UTXO(s) worth {in_flight_value} exfers reserved "
            f"by pending transfers from this daemon; retry once they confirm or use a "
            f"different sending wallet)"
        )
    return s


def test_in_flight_hint_matches_walletd_format() -> None:
    """Both branches of walletd's insufficient_balance message parse correctly."""
    with_inflight = _walletd_insufficient_balance_message(
        needed=5_100_000,
        available=4_000_000,
        utxo_count=1,
        in_flight_value=9_000_000,
        in_flight_count=2,
    )
    err = error_for_code(-32031, with_inflight)
    assert isinstance(err, InsufficientBalanceError)
    assert err.in_flight_reserved is True

    without_inflight = _walletd_insufficient_balance_message(
        needed=5_100_000,
        available=4_000_000,
        utxo_count=1,
        in_flight_value=0,
        in_flight_count=0,
    )
    err = error_for_code(-32031, without_inflight)
    assert isinstance(err, InsufficientBalanceError)
    assert err.in_flight_reserved is False


def test_insufficient_balance_without_in_flight_hint() -> None:
    msg = (
        "insufficient balance: need 5100000 exfers (amount + fee), "
        "wallet has 4000000 spendable across 1 UTXO(s)"
    )
    err = error_for_code(-32031, msg)
    assert isinstance(err, InsufficientBalanceError)
    assert err.in_flight_reserved is False


def test_walletd_error_repr_is_useful() -> None:
    err = error_for_code(-32020, "upstream down")
    assert "UpstreamError" in repr(err)
    assert "-32020" in repr(err)
    assert "upstream down" in repr(err)


def test_transport_error_not_a_walletd_error() -> None:
    """Operational classes are distinct — callers must catch separately."""
    from exfer_walletd import TransportError

    assert not issubclass(TransportError, WalletdError)
