"""
Простой ограничитель частоты запросов (скользящее окно).

Используется, чтобы не упираться в лимит запросов/минуту бесплатного тарифа
Gemini API (по умолчанию 15 запросов/мин — см. config.GEMINI_RPM). Если лимит
исчерпан, новые вызовы просто ждут своей очереди вместо падения с ошибкой 429.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque


class RateLimiter:
    def __init__(self, max_calls: int, period_seconds: float = 60.0):
        self.max_calls = max_calls
        self.period = period_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= self.period:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_calls:
                    self._timestamps.append(now)
                    return
                wait_time = self.period - (now - self._timestamps[0]) + 0.05
            await asyncio.sleep(max(wait_time, 0.05))
