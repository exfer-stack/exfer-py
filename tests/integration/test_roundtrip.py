"""End-to-end smoke tests against a real exfer-walletd binary.

Exercises only the walletd-local paths — anything that requires an
upstream node is skipped. The spawned walletd is pointed at a closed
loopback port so upstream-touching RPCs fail fast with -32020.
"""

from __future__ import annotations

import pytest

from exfer_walletd import (
    AuthenticationError,
    Client,
    UpstreamError,
)

pytestmark = pytest.mark.integration


def test_healthz_against_real_walletd(client: Client) -> None:
    assert client.healthz() is True


def test_ping_round_trips(client: Client) -> None:
    # Returns None on success; raises on failure.
    assert client.ping() is None


def test_generate_then_list_round_trips(client: Client) -> None:
    a = client.generate_address()["address"]
    b = client.generate_address()["address"]
    records = client.list_addresses()
    listed = [rec["address"] for rec in records]
    assert a in listed
    assert b in listed
    # Walletd returns records in ascending keystore-index order; pin that.
    # (Addresses are random 32-byte hashes, so they are NOT hex-sorted.)
    indices = [rec["index"] for rec in records if "index" in rec]
    assert indices == sorted(indices)


def test_wrong_token_raises_authentication_error(walletd_process: tuple[str, str]) -> None:
    url, _ = walletd_process
    with Client(url, "definitely-not-the-real-token") as c, pytest.raises(AuthenticationError):
        c.ping()


def test_upstream_unreachable_surfaces_typed_error(client: Client) -> None:
    """get_balance touches the upstream node, which we deliberately broke."""
    addr = client.generate_address()["address"]
    with pytest.raises(UpstreamError) as excinfo:
        client.get_balance(addr)
    # Walletd's message embeds the unreachable URL.
    assert "unreachable" in excinfo.value.message or "Connection" in excinfo.value.message


def test_invalid_address_rejected_before_upstream(client: Client) -> None:
    """Hex validation lives in the walletd wrapper layer (added in v0.4.1).

    The exception must be -32602 (InvalidParamsError), NOT -32020 — proves
    walletd never even tried to forward our garbage to the upstream node.
    """
    from exfer_walletd import InvalidParamsError

    with pytest.raises(InvalidParamsError):
        client.get_balance("not_hex_at_all")
