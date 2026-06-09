"""Spawn a real exfer-walletd binary for integration tests.

Two fixtures:

- ``walletd_process`` — plaintext HTTP on loopback. Yields
  ``(url, token, datadir)``.
- ``walletd_tls_process`` — HTTPS with `--tls`. Yields
  ``(url, token, fingerprint, datadir)``. Requires walletd >= 0.5.0.

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

from exfer_walletd import AsyncClient, Client

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


def _wait_for_healthz(url: str, timeout: float = 5.0, verify: bool = True) -> None:
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{url}/healthz", timeout=0.5, verify=verify)
            if r.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_exc = exc
        time.sleep(0.05)
    raise RuntimeError(f"walletd at {url} never became healthy: {last_exc}")


def _spawn_walletd(
    datadir: Path,
    port: int,
    tls: bool,
) -> subprocess.Popen[bytes]:
    """Run walletd and return the live Popen; caller waits for healthz."""
    binary = _walletd_binary()
    if binary is None:
        pytest.skip(
            "exfer-walletd binary not found; "
            "build it (`cargo build --release` in ../exfer-walletd) "
            "or set WALLETD_BINARY=<path>"
        )

    dead_node_port = _free_port()
    env = {
        **os.environ,
        "WALLETD_DATADIR": str(datadir),
        # walletd v1 encrypts the HD seed at rest (argon2id + ChaCha20-Poly1305)
        # and refuses to start without a passphrase. Supply a throwaway one for
        # the ephemeral per-test datadir; honor an externally-set value so a
        # custom keystore can still be used.
        "WALLETD_KEYSTORE_PASSPHRASE": os.environ.get(
            "WALLETD_KEYSTORE_PASSPHRASE", "integration-test-passphrase"
        ),
    }
    # walletd v1 derives addresses from an HD seed; a bare daemon start on an
    # empty datadir creates a *seedless* keyring, on which `generate_address`
    # errors. Initialise a seeded keystore first (one-shot; uses the same
    # datadir + passphrase from env).
    subprocess.run(
        [str(binary), "init-seeded"],
        env=env,
        check=True,
        capture_output=True,
    )
    args = [
        str(binary),
        "--bind",
        f"127.0.0.1:{port}",
        "--node-rpc",
        f"http://127.0.0.1:{dead_node_port}",
        "--upstream-attempts",
        "1",  # don't waste 3 seconds on each unreachable-node call
    ]
    if tls:
        args.append("--tls")

    return subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# Plaintext fixture — exists for tests that don't care about TLS
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def walletd_process(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[str, str]]:
    """Yield ``(url, token)`` for a freshly-spawned walletd (plaintext HTTP)."""
    datadir = tmp_path_factory.mktemp("walletd")
    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    proc = _spawn_walletd(datadir, port, tls=False)
    try:
        _wait_for_healthz(url)
    except RuntimeError:
        out, err = proc.communicate(timeout=2)
        proc.kill()
        raise RuntimeError(
            f"walletd failed to start.\nstdout:\n{out.decode()}\nstderr:\n{err.decode()}"
        ) from None

    # walletd v1 writes three scoped tokens (token-{read,manage,spend}); the
    # integration tests call generate_address, which is Manage scope.
    token = (datadir / "token-manage").read_text().strip()
    try:
        yield url, token
    finally:
        _terminate(proc)


@pytest.fixture
def client(walletd_process: tuple[str, str]) -> Iterator[Client]:
    url, token = walletd_process
    with Client(url, token) as c:
        yield c


# ---------------------------------------------------------------------------
# TLS fixture — covers the v0.5.0 --tls path
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def walletd_tls_process(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[str, str, str]]:
    """Yield ``(url, token, fingerprint)`` for a `--tls` walletd."""
    datadir = tmp_path_factory.mktemp("walletd-tls")
    port = _free_port()
    url = f"https://127.0.0.1:{port}"

    proc = _spawn_walletd(datadir, port, tls=True)
    try:
        # verify=False on the healthz probe — we don't have the cert yet.
        # Real client traffic will pin by fingerprint via the SDK.
        _wait_for_healthz(url, verify=False)
    except RuntimeError:
        out, err = proc.communicate(timeout=2)
        proc.kill()
        raise RuntimeError(
            f"walletd --tls failed to start.\nstdout:\n{out.decode()}\nstderr:\n{err.decode()}"
        ) from None

    # walletd v1 writes three scoped tokens (token-{read,manage,spend}); the
    # integration tests call generate_address, which is Manage scope.
    token = (datadir / "token-manage").read_text().strip()
    fingerprint = (datadir / "cert.fingerprint").read_text().strip()
    try:
        yield url, token, fingerprint
    finally:
        _terminate(proc)


@pytest.fixture
def tls_client(walletd_tls_process: tuple[str, str, str]) -> Iterator[Client]:
    url, token, fingerprint = walletd_tls_process
    with Client(url, token, fingerprint=fingerprint) as c:
        yield c


@pytest.fixture
async def async_tls_client(
    walletd_tls_process: tuple[str, str, str],
) -> Iterator[AsyncClient]:
    url, token, fingerprint = walletd_tls_process
    async with AsyncClient(url, token, fingerprint=fingerprint) as c:
        yield c
