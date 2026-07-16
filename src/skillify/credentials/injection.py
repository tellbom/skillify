"""Per-process credential injection primitives."""

from __future__ import annotations

import os
import re
import socket
import threading
from pathlib import Path


_ENV_NAME = re.compile(r"SKILLIFY_MCP_[A-Z0-9]+(?:_[A-Z0-9]+)*\Z")


def injected_environment(base: dict[str, str], name: str, secret: str) -> dict[str, str]:
    if _ENV_NAME.fullmatch(name) is None or not secret:
        raise ValueError("credential injection requires an approved environment name")
    return {**base, name: secret}


class UnixSocketSecretServer:
    """Serve one in-memory secret over a task-local Unix socket."""

    def __init__(self, path: Path, secret: str) -> None:
        self.path = Path(path)
        self.secret = secret
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "UnixSocketSecretServer":
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.unlink(missing_ok=True)
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.bind(str(self.path))
        self.path.chmod(0o600)
        self._socket.listen(1)

        def serve() -> None:
            assert self._socket is not None
            connection, _ = self._socket.accept()
            with connection:
                connection.sendall(self.secret.encode())

        self._thread = threading.Thread(target=serve, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self.path.unlink(missing_ok=True)


def read_unix_socket(path: Path) -> str:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(path))
        return client.recv(64 * 1024).decode()
    finally:
        client.close()
