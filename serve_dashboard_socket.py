"""Run the browser dashboard on an owner-only Unix socket, without TCP ingress.

Use with the dashboard-private Compose profile. The host's trusted Tailscale
Serve process may connect to the socket; no public or host loopback port is
opened. This does not protect against other processes running as the owner.
"""

import errno
import os
import socket
import stat
from pathlib import Path

SOCKET = Path(os.environ.get("HQ_SOCKET", "/sockets/fitness-hq.sock"))


def bind_private_socket(path: Path) -> socket.socket:
    path = Path(path)
    if path.parent.is_symlink():
        raise RuntimeError("Socket directory must not be a symbolic link")
    if not path.parent.is_dir():
        raise RuntimeError("Socket directory does not exist")
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            raise RuntimeError("Refusing symbolic-link socket path")
        info = path.stat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("Refusing non-socket or non-owned socket path")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            try:
                probe.connect(str(path))
            except OSError as exc:
                if exc.errno not in {errno.ECONNREFUSED, errno.ENOENT}:
                    raise
            else:
                raise RuntimeError("The dashboard socket is already serving")
        path.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(path))
        path.chmod(0o600)
        listener.listen(128)
        return listener
    except BaseException:
        listener.close()
        raise


def main() -> None:
    import uvicorn

    os.umask(0o077)
    listener = bind_private_socket(SOCKET)
    inode = SOCKET.stat().st_ino
    try:
        config = uvicorn.Config(
            "app:app", access_log=False, log_level="warning", proxy_headers=False
        )
        uvicorn.Server(config).run(sockets=[listener])
    finally:
        listener.close()
        if SOCKET.exists() and SOCKET.stat().st_ino == inode:
            SOCKET.unlink()


if __name__ == "__main__":
    main()
