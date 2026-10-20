"""Einfacher In-Process-Eventbus für WebSocket-Live-Updates (Jobs, Genehmigungen, Benachrichtigungen)."""
from __future__ import annotations

import asyncio
import time
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[int, tuple[asyncio.Queue, bool]] = {}
        self._next = 0
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def subscribe(self, admin: bool) -> tuple[int, asyncio.Queue]:
        self._next += 1
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs[self._next] = (q, admin)
        return self._next, q

    def unsubscribe(self, sid: int) -> None:
        self._subs.pop(sid, None)

    def publish(self, kind: str, data: Any, admin_only: bool = False) -> None:
        """Thread-sicher: synchrone API-Handler laufen im Threadpool, die Queues gehören zur Event-Loop."""
        event = {"type": kind, "ts": time.time(), "data": data}
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self.loop is not None and running is not self.loop:
            if not self.loop.is_closed():
                self.loop.call_soon_threadsafe(self._deliver, event, admin_only)
            return
        self._deliver(event, admin_only)

    def _deliver(self, event: dict, admin_only: bool) -> None:
        for q, admin in list(self._subs.values()):
            if admin_only and not admin:
                continue
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
