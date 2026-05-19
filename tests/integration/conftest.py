"""Spawn a real exfer-walletd binary for integration tests.

We point ``--node-rpc`` at a closed loopback port so any RPC that *would*
touch the upstream node fails fast — the tests here exercise only the
walletd-local paths (``healthz``, ``ping``, ``generate_address``,
``list_addresses``, scope rejection). Tests that need a live node are
marked ``@pytest.mark.requires_node`` and skipped here.

Pointing at the locally-built ``exfer-walletd`` binary requires the
sibling repo to have been built (``cargo build --release`` in
``../exfer-walletd``). Override with ``WALLETD_BINARY=/path/to/exfer-walletd``
if walletd is installed somewhere else. If the binary is unavailable, the
integration tests skip cleanly rather than fail.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from exfer_walletd import Client

DEFAULT_BINARY = (
    Path(__file__).resolve().parents[2].parent
    / "exfer-walletd"
    / "target"
    / "release"
    / "exfer-walletd"
)


def _free_port() -> int:
    """Grab an unused TCP port. Race-prone but fine for our scale."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _walletd_binary() -> Path | None:
    override = os.environ.get("WALLETD_BINARY")
    if override:
        path = Path(override)
        return path if path.is_file() and os.access(path, os.X_OK) else None
    return DEFAULT_BINARY if DEFAULT_BINARY.is_file() else None


def _wait_for_healthz(url: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{url}/healthz", timeout=0.5)
            if r.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_exc = exc
        time.sleep(0.05)
    raise RuntimeError(f"walletd at {url} never became healthy: {last_exc}")


@pytest.fixture(scope="module")
def walletd_process(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, str]]:
    """Yield ``(url, token)`` for a freshly-spawned walletd.

    Module-scoped so we pay the startup once per test file rather than per
    test function. The datadir is throwaway and gets cleaned up by pytest.
    """
    binary = _walletd_binary()
    if binary is None:
        pytest.skip(
            "exfer-walletd binary not found; "
            "build it (`cargo build --release` in ../exfer-walletd) "
            "or set WALLETD_BINARY=<path>"
        )

    datadir = tmp_path_factory.mktemp("walletd")
    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    # Point at a port nothing is listening on so upstream-touching RPCs
    # fail fast instead of stalling.
    dead_node_port = _free_port()

    env = {**os.environ, "WALLETD_DATADIR": str(datadir)}
    proc = subprocess.Popen(
        [
            str(binary),
            "--bind",
            f"127.0.0.1:{port}",
            "--node-rpc",
            f"http://127.0.0.1:{dead_node_port}",
            "--upstream-attempts",
            "1",  # don't waste 3 seconds on each unreachable-node call
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_healthz(url)
    except RuntimeError:
        out, err = proc.communicate(timeout=2)
        proc.kill()
        raise RuntimeError(
            f"walletd failed to start.\nstdout:\n{out.decode()}\nstderr:\n{err.decode()}"
        ) from None

    token = (datadir / "token").read_text().strip()
    try:
        yield url, token
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def client(walletd_process: tuple[str, str]) -> Iterator[Client]:
    url, token = walletd_process
    with Client(url, token) as c:
        yield c
