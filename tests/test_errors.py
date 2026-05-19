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
