"""One UI action at a time, most urgent first.

Meet's page is one shared surface: a chat post, a mic click and a People-panel read must not interleave, but the mic must
never sit behind the others. So every action is split into short critical sections (a single find, click or fill) and
anything that only waits (sleeping, polling a box) happens outside them. Waiting sections are served by priority, then in
arrival order, so a mic request waits for at most the one primitive already running.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import time
from collections import deque
from contextlib import asynccontextmanager

MIC, CHAT_POST, CHAT_READ, ADMIT, PEOPLE = range(5)  # lower = more urgent


class UIScheduler:
    def __init__(self) -> None:
        self._busy = False
        self._queue: list[tuple[int, int, asyncio.Future]] = []
        self._seq = itertools.count()
        self.waits: deque[tuple[int, float]] = deque(maxlen=200)  # (priority, seconds waited) of recent sections

    async def acquire(self, priority: int) -> None:
        t0 = time.monotonic()
        if self._busy or self._queue:
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            heapq.heappush(self._queue, (priority, next(self._seq), fut))
            try:
                await fut
            except asyncio.CancelledError:
                if fut.done() and not fut.cancelled():  # we were handed the lock just as we were cancelled
                    self.release()
                raise
        else:
            self._busy = True
        self.waits.append((priority, time.monotonic() - t0))

    def release(self) -> None:
        while self._queue:
            _, _, fut = heapq.heappop(self._queue)
            if not fut.cancelled():
                fut.set_result(None)  # hand over: the lock stays busy
                return
        self._busy = False

    @asynccontextmanager
    async def section(self, priority: int):
        await self.acquire(priority)
        try:
            yield
        finally:
            self.release()
