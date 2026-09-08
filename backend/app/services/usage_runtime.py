"""Same-host process ownership for pending calls, including rolling deployments.

Each process holds an OS lock until shutdown. Locks are released by the OS on a
crash, so request age is never used to decide whether another process is alive.
All instances sharing a database on this host must use USAGE_RUNTIME_DIR. Other
hosts/directories have distinct namespaces and are deliberately not recovered.
Lock files must not be unlinked: that could give two processes different inodes.
"""

import hashlib
import os
from pathlib import Path
import re
import socket
from typing import BinaryIO
import uuid


_current_runtime_id: str | None = None


def current_runtime_id() -> str | None:
    return _current_runtime_id


def _lock_file(path: Path) -> BinaryIO | None:
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                handle.close()
                return None
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                return None
        return handle
    except BaseException:
        handle.close()
        raise


def release_lock(handle: BinaryIO) -> None:
    # Closing a descriptor releases its lock on both Windows and Linux.
    handle.close()


class UsageRuntime:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        scope = f"{socket.gethostname()}:{os.path.normcase(str(self.directory))}"
        self.namespace = hashlib.sha256(scope.encode()).hexdigest()[:16]
        self.id = f"{self.namespace}-{uuid.uuid4().hex}"
        self._handle: BinaryIO | None = None

    def start(self) -> None:
        global _current_runtime_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self._handle = _lock_file(self.directory / f"{self.id}.lock")
        if self._handle is None:
            raise RuntimeError("Unable to acquire unique usage runtime ownership")
        _current_runtime_id = self.id

    def stop(self) -> None:
        global _current_runtime_id
        if _current_runtime_id == self.id:
            _current_runtime_id = None
        if self._handle is not None:
            release_lock(self._handle)
            self._handle = None

    def try_claim_abandoned(self, owner_id: str) -> BinaryIO | None:
        if (
            owner_id == self.id
            or not re.fullmatch(r"[0-9a-f]{16}-[0-9a-f]{32}", owner_id)
            or not owner_id.startswith(f"{self.namespace}-")
        ):
            return None
        return _lock_file(self.directory / f"{owner_id}.lock")
