"""
plr_ivoryos.async_bridge
=========================
A single, long-lived asyncio event loop running on a daemon background thread.

All PLR coroutines are submitted here via run_async(), which blocks the calling
(IvoryOS script-runner) thread until the coroutine completes.  This avoids the
"closed loop" problem that arises from using asyncio.run() for long-lived hardware
connections, and has zero interaction with Flask or SocketIO.
"""

import asyncio
import concurrent.futures
import threading
from typing import Any, Awaitable, TypeVar

_T = TypeVar("_T")

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


def get_loop() -> asyncio.AbstractEventLoop:
    """Return (or lazily create) the shared background event loop."""
    global _loop, _thread
    with _lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            _thread = threading.Thread(
                target=_loop.run_forever,
                daemon=True,
                name="plr-ivoryos-asyncio",
            )
            _thread.start()
    return _loop


def run_async(coro: Awaitable[_T]) -> _T:
    """
    Submit a PLR coroutine to the shared loop and block until it completes.

    Safe to call from any thread (including the IvoryOS Flask/script-runner
    thread).  Propagates exceptions normally.
    """
    future: concurrent.futures.Future[_T] = asyncio.run_coroutine_threadsafe(
        coro, get_loop()
    )
    return future.result()


def shutdown() -> None:
    """Gracefully stop the shared event loop (called on app teardown)."""
    global _loop, _thread
    with _lock:
        if _loop and not _loop.is_closed():
            _loop.call_soon_threadsafe(_loop.stop)
        _loop = None
        _thread = None
