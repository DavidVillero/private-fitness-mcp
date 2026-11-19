"""Synthetic owner-only socket contract; no service or user data is touched."""

import os
import socket
import stat
import tempfile
from pathlib import Path

import pytest

from serve_dashboard_socket import bind_private_socket


@pytest.fixture
def socket_directory():
    # AF_UNIX paths are limited to roughly 100 bytes on macOS. pytest temp
    # paths include long test names, so use a private, short-lived directory.
    with tempfile.TemporaryDirectory(prefix="pf-uds-", dir="/tmp") as folder:
        yield Path(folder)


def test_dashboard_unix_socket_has_no_tcp_listener(socket_directory):
    directory = socket_directory / "sockets"
    directory.mkdir(mode=0o700)
    path = directory / "test.sock"
    listener = bind_private_socket(path)
    try:
        assert stat.S_ISSOCK(path.stat().st_mode)
        assert path.stat().st_mode & 0o777 == 0o600
        assert listener.family == socket.AF_UNIX
        with pytest.raises(RuntimeError, match="already serving"):
            bind_private_socket(path)
    finally:
        listener.close()


def test_dashboard_socket_refuses_regular_files_and_symlinks(socket_directory):
    directory = socket_directory / "sockets"
    directory.mkdir(mode=0o700)
    regular = directory / "existing.sock"
    regular.write_text("synthetic")
    with pytest.raises(RuntimeError, match="non-socket"):
        bind_private_socket(regular)
    alias = directory / "alias.sock"
    alias.symlink_to(regular)
    with pytest.raises(RuntimeError, match="symbolic-link"):
        bind_private_socket(alias)


def test_dashboard_socket_replaces_only_stale_owned_socket(socket_directory):
    directory = socket_directory / "sockets"
    directory.mkdir(mode=0o700)
    path = directory / "stale.sock"
    first = bind_private_socket(path)
    first.close()
    second = bind_private_socket(path)
    second.close()
    assert path.stat().st_uid == os.getuid()


def test_native_dashboard_serves_http_and_enforces_owner(socket_directory):
    """Exercise the actual launcher on the host; no DB or Tailscale is used."""
    import subprocess
    import sys
    import time

    import httpx

    root = Path(__file__).resolve().parents[1]
    path = socket_directory / "http.sock"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("HQ_", "FITNESS_", "CONTEXT_"))
    }
    env.update(
        HQ_SOCKET=str(path),
        HQ_STATE=str(socket_directory / "state"),
        HQ_OWNER="owner@example.invalid",
        HQ_ORIGIN="https://fitness.example.invalid",
        PYTHONPATH=str(root / "services/private-fitness-mcp"),
    )
    with (socket_directory / "server.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, str(root / "serve_dashboard_socket.py")],
            env=env,
            cwd=root,
            stdout=log,
            stderr=log,
        )
        try:
            with httpx.Client(
                transport=httpx.HTTPTransport(uds=str(path)),
                base_url="http://fitness.example.invalid",
                timeout=3,
            ) as client:
                for _ in range(100):
                    assert process.poll() is None, "Synthetic dashboard exited"
                    try:
                        if client.get("/healthz").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.05)
                else:
                    pytest.fail("Synthetic dashboard did not start")
                assert client.get("/").status_code == 401
                assert (
                    client.get(
                        "/", headers={"tailscale-user-login": "other@example.invalid"}
                    ).status_code
                    == 401
                )
                assert (
                    client.get(
                        "/", headers={"tailscale-user-login": "owner@example.invalid"}
                    ).status_code
                    == 200
                )
                assert path.stat().st_mode & 0o777 == 0o600
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    # Uvicorn may re-raise SIGTERM before Python finally blocks run. A stale
    # owner-matching socket must be recoverable without deleting live sockets.
    restarted = bind_private_socket(path)
    restarted.close()
