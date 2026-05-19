"""End-to-end TLS tests against `exfer-walletd --tls`.

Spawns walletd with `--tls`, points the SDK at the HTTPS URL with the
auto-generated fingerprint, and verifies every wire happy path still
works through the TLS layer. The mismatch case constructs a Client
with one bit of the fingerprint flipped and asserts
:class:`FingerprintMismatchError`.
"""

from __future__ import annotations

import pytest

from exfer_walletd import (
    AsyncClient,
    Client,
    FingerprintMismatchError,
    InvalidParamsError,
    TransportError,
    UpstreamError,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_healthz_works_over_tls(tls_client: Client) -> None:
    assert tls_client.healthz() is True


def test_ping_works_over_tls(tls_client: Client) -> None:
    assert tls_client.ping() is None


def test_generate_and_list_addresses_over_tls(tls_client: Client) -> None:
    addr = tls_client.generate_address()
    assert isinstance(addr, str)
    assert addr in tls_client.list_addresses()


def test_invalid_params_still_typed_over_tls(tls_client: Client) -> None:
    with pytest.raises(InvalidParamsError):
        tls_client.get_balance("not_hex_at_all")


def test_upstream_error_surfaces_over_tls(tls_client: Client) -> None:
    addr = tls_client.generate_address()
    with pytest.raises(UpstreamError):
        # walletd is pointed at a closed port for upstream
        tls_client.get_balance(addr)


# ---------------------------------------------------------------------------
# Async mirror — single smoke check, sync path is exhaustive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_client_works_over_tls(async_tls_client: AsyncClient) -> None:
    assert await async_tls_client.healthz() is True
    assert await async_tls_client.ping() is None
    addr = await async_tls_client.generate_address()
    assert addr in (await async_tls_client.list_addresses())


# ---------------------------------------------------------------------------
# Negative path — pinning catches the wrong cert
# ---------------------------------------------------------------------------


def _flip_one_bit(fp: str) -> str:
    """Toggle one nibble of the hex digest so it's clearly different."""
    prefix, _, digest = fp.partition(":")
    head, tail = digest[:-1], digest[-1]
    flipped = "f" if tail != "f" else "0"
    return f"{prefix}:{head}{flipped}"


def test_wrong_fingerprint_raises_mismatch(
    walletd_tls_process: tuple[str, str, str],
) -> None:
    url, token, real_fp = walletd_tls_process
    wrong_fp = _flip_one_bit(real_fp)
    assert wrong_fp != real_fp

    with (
        Client(url, token, fingerprint=wrong_fp) as c,
        pytest.raises(FingerprintMismatchError) as excinfo,
    ):
        c.ping()
    assert excinfo.value.expected == wrong_fp
    assert excinfo.value.actual == real_fp


def test_pinned_client_against_http_walletd_raises_transport_error(
    walletd_process: tuple[str, str],
) -> None:
    """Pinning is set, but walletd is plain HTTP. Constructor blocks it."""
    url, token = walletd_process  # http://
    real_fp = "sha256:" + ("ab" * 32)
    with pytest.raises(ValueError, match="requires an https:// URL"):
        Client(url, token, fingerprint=real_fp)


def test_mismatch_is_catchable_as_transport_error(
    walletd_tls_process: tuple[str, str, str],
) -> None:
    """FingerprintMismatchError must be caught by `except TransportError`."""
    url, token, real_fp = walletd_tls_process
    with (
        Client(url, token, fingerprint=_flip_one_bit(real_fp)) as c,
        pytest.raises(
            TransportError  # FingerprintMismatchError subclass
        ),
    ):
        c.ping()
