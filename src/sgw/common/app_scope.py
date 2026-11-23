"""Objects that belong to one FastAPI app instance: built lazily on first use, kept on `app.state`, and closed
when that app's lifespan ends. Nothing here is process-global, so a second app (another database, another
scenario clock) never reuses the first app's pool or services."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

CLOSERS = "sgw_scoped_closers"
_lock = threading.Lock()


def per_app[T](app: Any, name: str, build: Callable[[], T], close: Callable[[T], Any] | None = None) -> T:
    """`app.state.<name>`, built once per app; `close(value)` runs at `close_all(app)`."""
    with _lock:
        value = getattr(app.state, name, None)
        if value is None:
            value = build()
            setattr(app.state, name, value)
            if close is not None:
                _register(app, name, close, value)
        return value


def _register(app: Any, name: str, close: Callable[[Any], Any], value: Any) -> None:
    closers = getattr(app.state, CLOSERS, None)
    if closers is None:
        closers = []
        setattr(app.state, CLOSERS, closers)
    closers.append((name, close, value))


def on_close(app: Any, name: str, close: Callable[[Any], Any], value: Any) -> None:
    """Close `value` (kept as `app.state.<name>`) when `close_all(app)` runs."""
    with _lock:
        _register(app, name, close, value)


async def close_all(app: Any) -> None:
    """Closes and forgets every scoped object of `app` (newest first); a failing close is logged."""
    with _lock:
        closers: list[tuple[str, Callable[[Any], Any], Any]] = list(getattr(app.state, CLOSERS, None) or [])
        setattr(app.state, CLOSERS, [])
        for name, _, _ in closers:
            setattr(app.state, name, None)
    for name, close, value in reversed(closers):
        try:
            if inspect.iscoroutinefunction(close):
                await close(value)
            else:
                await asyncio.to_thread(close, value)
        except Exception:
            log.warning("closing %s failed", name, exc_info=True)
