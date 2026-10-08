"""Advisory single-writer process locks for durable trading ledgers (POSIX).

Do not use a portable 'pid file only' lock: stale pid files after SIGKILL would
require unsafe manual deletion, and O_EXCL alone does not prove owner liveness.
This project deploys on Linux containers/Termux, where flock auto-releases on exit.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None


class AlreadyRunning(RuntimeError):
    pass


class ProcessLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.fd: int | None = None

    def acquire(self):
        if fcntl is None:
            raise AlreadyRunning("Running a stateful bot requires POSIX file locking")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode())
            os.fsync(fd)
        except (OSError, BlockingIOError) as exc:
            os.close(fd)
            raise AlreadyRunning(f"Another VORTEX worker is using {self.path}") from exc
        self.fd = fd
        return self

    def release(self):
        if self.fd is not None:
            if fcntl is not None:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()
