"""Thread-safe fan-out of live messages to WebSocket subscribers.

The CV pipeline runs in a plain thread; WebSocket handlers live on the asyncio
loop. `publish` may be called from any thread.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from app.utils.logger import get_logger

log = get_logger("bus")


class EventBus:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, msg_type: str, data: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed() or not self._subscribers:
            return
        message = {"type": msg_type, "data": data}
        try:
            loop.call_soon_threadsafe(self._fanout, message)
        except RuntimeError:
            pass

    def _fanout(self, message: dict) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            if q.full():
                try:
                    q.get_nowait()  # drop oldest for slow clients
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(message)


event_bus = EventBus()
