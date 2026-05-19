"""Shared pytest fixtures.

We use ``respx`` to mock walletd at the httpx layer — no sockets, no
process spawning. Integration tests under ``tests/integration/`` spawn
a real walletd binary and are marked ``@pytest.mark.integration``.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx

from exfer_walletd import Client

WALLETD_URL = "http://walletd.test"
TOKEN = "test-token"


@pytest.fixture
def mock_walletd() -> Iterator[respx.MockRouter]:
    """Mock walletd at the httpx layer.

    Yields a :class:`respx.MockRouter` rooted at :data:`WALLETD_URL` so
    tests can stub each endpoint independently.
    """
    with respx.mock(base_url=WALLETD_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
def client(mock_walletd: respx.MockRouter) -> Iterator[Client]:
    """A sync :class:`Client` wired to the mock router."""
    with Client(WALLETD_URL, TOKEN) as c:
        yield c


def rpc_ok(result: object, *, request_id: int = 1) -> httpx.Response:
    """Build a successful JSON-RPC response body."""
    return httpx.Response(200, json={"jsonrpc": "2.0", "result": result, "id": request_id})


def rpc_err(code: int, message: str, *, status: int = 200, request_id: int = 1) -> httpx.Response:
    """Build a JSON-RPC error response body."""
    return httpx.Response(
        status,
        json={
            "jsonrpc": "2.0",
            "error": {"code": code, "message": message},
            "id": request_id,
        },
    )
