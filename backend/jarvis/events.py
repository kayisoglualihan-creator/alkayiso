"""Einfacher In-Process-Eventbus für WebSocket-Live-Updates (Jobs, Genehmigungen, Benachrichtigungen)."""
from __future__ import annotations

import asyncio
import time
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[int, tuple[asyncio.Queue, bool]] = {}
        self._next = 0

    def subscribe(self, admin: bool) -> tuple[int, asyncio.Queue]:
        self._next += 1
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs[self._next] = (q, admin)
        return self._next, q

    def unsubscribe(self, sid: int) -> None:
        self._subs.pop(sid, None)

    def publish(self, kind: str, data: Any, admin_only: bool = False) -> None:
        event = {"type": kind, "ts": time.time(), "data": data}
        for q, admin in list(self._subs.values()):
            if admin_only and not admin:
                continue
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
