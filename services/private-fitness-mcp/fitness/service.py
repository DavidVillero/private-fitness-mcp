"""Project-owned ingestion service restricted to an owner-only Unix-domain socket."""

import errno
import argparse
import os
import socket
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOCKET = ROOT / "secrets/ingest.sock"


def bind_private_socket(path):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError("Socket path must not be a symlink")
    if path.exists():
        info = path.stat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("Refusing to replace a path not owned by this service")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            try:
                probe.connect(str(path))
            except OSError as e:
                if e.errno not in [errno.ECONNREFUSED, errno.ENOENT]:
                    raise
            else:
                raise RuntimeError("The ingestion socket is already serving")
        path.unlink()  # Only a stale, owner-matching socket is replaced.
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(path))
        os.chmod(path, 0o600)
        listener.listen(128)
        listener.set_inheritable(True)
        return listener
    except BaseException:
        listener.close()
        raise


def main():
    import uvicorn
    from .api import create_app

    parser = argparse.ArgumentParser()
    parser.add_argument("--loopback-port", type=int, choices=[8765])
    args = parser.parse_args()
    os.umask(0o077)
    if SOCKET.parent.is_symlink():
        raise RuntimeError("Secrets directory must not be a symlink")
    SOCKET.parent.mkdir(mode=0o700, exist_ok=True)
    SOCKET.parent.chmod(0o700)
    app = create_app(None, ROOT / "secrets/phone-token")
    if args.loopback_port is not None:
        # Explicitly approved fallback for macOS Tailscale's Unix-socket sandbox restriction.
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=args.loopback_port,
            access_log=False,
            log_level="warning",
        )
        return
    # Supplying the socket prevents Uvicorn's default UDS chmod(0666).
    listener = bind_private_socket(SOCKET)
    inode = SOCKET.stat().st_ino
    try:
        server = uvicorn.Server(
            uvicorn.Config(app, access_log=False, log_level="warning")
        )
        server.run(sockets=[listener])
    finally:
        listener.close()
        if SOCKET.exists() and SOCKET.stat().st_ino == inode:
            SOCKET.unlink()


if __name__ == "__main__":
    main()
