from __future__ import annotations

import queue
import threading
from concurrent.futures import Future, TimeoutError
from dataclasses import replace
from typing import Any

from .browser_reader import BrowserSettings, NeurogateUsageReader
from .models import UsageSnapshot


WORKER_QUEUE_MAXSIZE = 4
WORKER_CALL_TIMEOUT_SECONDS = 90
WORKER_STOP_TIMEOUT_SECONDS = 15


class ThreadedUsageReader:
    """Runs Playwright reader operations on one dedicated thread.

    Playwright sync objects are thread-bound. The UI can call this wrapper from
    any helper thread, but the real browser context is always touched only by
    the worker thread.
    """

    def __init__(self, settings: BrowserSettings) -> None:
        self._settings = replace(settings)
        self._keep_browser_open = not settings.headless
        self._commands: queue.Queue[tuple[str, tuple[Any, ...], Future[Any] | None]] = queue.Queue(
            maxsize=WORKER_QUEUE_MAXSIZE
        )
        self._preload_refresh: Future[Any] | None = None
        self._thread = threading.Thread(target=self._run, name="neurogate-reader", daemon=True)
        self._thread.start()
        self._preload_refresh = self._enqueue("refresh")

    @property
    def keep_browser_open(self) -> bool:
        return self._keep_browser_open

    def refresh(self) -> UsageSnapshot:
        if self._preload_refresh is not None:
            future = self._preload_refresh
            self._preload_refresh = None
            return future.result()
        return self._call("refresh")

    def set_keep_browser_open(self, enabled: bool) -> None:
        self._keep_browser_open = enabled
        self._call("set_keep_browser_open", enabled)

    def reset_account_session(self) -> None:
        self._call("reset_account_session")

    def stop(self) -> None:
        future: Future[Any] = Future()
        self._put_command("stop", (), future)
        try:
            future.result(timeout=WORKER_STOP_TIMEOUT_SECONDS)
        finally:
            if self._thread.is_alive():
                self._thread.join(timeout=5)

    def _call(self, name: str, *args: Any) -> Any:
        future = self._enqueue(name, *args)
        try:
            return future.result(timeout=WORKER_CALL_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            future.cancel()
            raise RuntimeError(f"Reader worker command timed out: {name}") from exc

    def _enqueue(self, name: str, *args: Any) -> Future[Any]:
        future: Future[Any] = Future()
        self._put_command(name, args, future)
        return future

    def _put_command(self, name: str, args: tuple[Any, ...], future: Future[Any]) -> None:
        try:
            self._commands.put((name, args, future), timeout=1)
        except queue.Full as exc:
            raise RuntimeError(f"Reader worker queue is full: {name}") from exc

    def _run(self) -> None:
        reader = NeurogateUsageReader(self._settings)
        while True:
            name, args, future = self._commands.get()
            try:
                if name == "stop":
                    reader.stop()
                    if future:
                        future.set_result(None)
                    return
                if name == "refresh":
                    result = reader.refresh()
                elif name == "set_keep_browser_open":
                    result = reader.set_keep_browser_open(bool(args[0]))
                elif name == "reset_account_session":
                    result = reader.reset_account_session()
                else:
                    raise RuntimeError(f"Unknown reader command: {name}")
            except Exception as exc:  # noqa: BLE001 - propagate operational errors to the caller.
                if future and not future.cancelled():
                    future.set_exception(exc)
            else:
                if future and not future.cancelled():
                    future.set_result(result)
