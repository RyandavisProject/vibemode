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
WorkerCommand = tuple[str, tuple[Any, ...], Future[Any] | None]


class ThreadedUsageReader:
    """Runs Playwright reader operations on one dedicated thread.

    Playwright sync objects are thread-bound. The UI can call this wrapper from
    any helper thread, but the real browser context is always touched only by
    the worker thread.
    """

    def __init__(self, settings: BrowserSettings) -> None:
        self._settings = replace(settings)
        self._keep_browser_open = not settings.headless
        self._worker_lock = threading.Lock()
        self._future_queues: dict[Future[Any], queue.Queue[WorkerCommand]] = {}
        self._preload_refresh: Future[Any] | None = None
        self._start_worker()
        self._preload_refresh = self._enqueue("refresh")

    @property
    def keep_browser_open(self) -> bool:
        return self._keep_browser_open

    def refresh(self, force_session_recovery: bool = False) -> UsageSnapshot:
        if not force_session_recovery and self._preload_refresh is not None:
            future = self._preload_refresh
            self._preload_refresh = None
            return self._wait_for_result("refresh", future)
        if force_session_recovery:
            return self._call("refresh", True)
        return self._call("refresh")

    def set_keep_browser_open(self, enabled: bool) -> None:
        self._keep_browser_open = enabled
        self._settings = replace(
            self._settings,
            headless=not enabled,
            hide_after_successful_login=not enabled,
            show_browser_on_login=enabled,
        )
        self._call("set_keep_browser_open", enabled)

    def reset_account_session(self) -> None:
        self._call("reset_account_session")

    def stop(self) -> None:
        future: Future[Any] = Future()
        with self._worker_lock:
            command_queue = self._commands
        self._put_command(command_queue, "stop", (), future)
        try:
            future.result(timeout=WORKER_STOP_TIMEOUT_SECONDS)
        finally:
            if self._thread.is_alive():
                self._thread.join(timeout=5)

    def _call(self, name: str, *args: Any) -> Any:
        future = self._enqueue(name, *args)
        return self._wait_for_result(name, future)

    def _wait_for_result(self, name: str, future: Future[Any]) -> Any:
        try:
            return future.result(timeout=WORKER_CALL_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            future.cancel()
            self._restart_worker_after_timeout(name, future)
            raise RuntimeError(f"Reader worker command timed out: {name}") from exc
        finally:
            with self._worker_lock:
                self._future_queues.pop(future, None)

    def _enqueue(self, name: str, *args: Any) -> Future[Any]:
        future: Future[Any] = Future()
        with self._worker_lock:
            command_queue = self._commands
            self._future_queues[future] = command_queue
        try:
            self._put_command(command_queue, name, args, future)
        except Exception:
            with self._worker_lock:
                self._future_queues.pop(future, None)
            raise
        return future

    def _put_command(
        self,
        command_queue: queue.Queue[WorkerCommand],
        name: str,
        args: tuple[Any, ...],
        future: Future[Any] | None,
    ) -> None:
        try:
            command_queue.put((name, args, future), timeout=1)
        except queue.Full as exc:
            raise RuntimeError(f"Reader worker queue is full: {name}") from exc

    def _start_worker(self) -> None:
        self._commands: queue.Queue[WorkerCommand] = queue.Queue(maxsize=WORKER_QUEUE_MAXSIZE)
        self._thread = threading.Thread(
            target=self._run,
            args=(self._commands,),
            name="neurogate-reader",
            daemon=True,
        )
        self._thread.start()

    def _restart_worker_after_timeout(self, name: str, future: Future[Any]) -> None:
        with self._worker_lock:
            timed_out_queue = self._future_queues.get(future)
            if timed_out_queue is None:
                return
            if timed_out_queue is not self._commands:
                return
            self._retire_command_queue(timed_out_queue, name)
            self._start_worker()

    def _retire_command_queue(self, command_queue: queue.Queue[WorkerCommand], timed_out_name: str) -> None:
        while True:
            try:
                _name, _args, pending_future = command_queue.get_nowait()
            except queue.Empty:
                break
            if pending_future and not pending_future.done():
                pending_future.set_exception(
                    RuntimeError(f"Reader worker restarted after timeout: {timed_out_name}")
                )
            if pending_future:
                self._future_queues.pop(pending_future, None)
        if self._preload_refresh is not None and self._future_queues.get(self._preload_refresh) is command_queue:
            self._preload_refresh.cancel()
            self._future_queues.pop(self._preload_refresh, None)
            self._preload_refresh = None
        command_queue.put_nowait(("stop", (), None))

    def _run(self, command_queue: queue.Queue[WorkerCommand]) -> None:
        reader = NeurogateUsageReader(self._settings)
        while True:
            name, args, future = command_queue.get()
            try:
                if name == "stop":
                    reader.stop()
                    if future:
                        future.set_result(None)
                    return
                if name == "refresh":
                    result = reader.refresh(*args)
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
