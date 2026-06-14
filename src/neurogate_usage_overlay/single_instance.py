from __future__ import annotations

from pathlib import Path


class SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if _lock_file(handle):
                self._handle = handle
                return True
        except Exception:
            handle.close()
            raise

        handle.close()
        return False

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            _unlock_file(self._handle)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> SingleInstanceLock:
        if not self.acquire():
            raise RuntimeError(f"Another overlay instance already holds {self.path}")
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.release()


def _lock_file(handle) -> bool:
    handle.seek(0)
    if _IS_WINDOWS:
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock_file(handle) -> None:
    handle.seek(0)
    if _IS_WINDOWS:
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


_IS_WINDOWS = __import__("os").name == "nt"
