"""Keeping model calls under the providers' free-tier limits.

Each model in data/models.toml has a limit of requests per minute, per day, and at once. Calls
wait for room in the minute rather than be refused, and a day's requests are counted in a file,
so the count lasts across runs. When the day's share is used up, or the provider says its daily
quota is, the call fails with BudgetUsedUp and the step that made it passes to the next.

Days are counted in Pacific standard time, when Google resets its daily quotas. During summer
time the real reset comes an hour before v2 counts a new day, which errs on the safe side.
"""

import asyncio
import json
import math
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from bi2.core.errors import BudgetUsedUp
from bi2.llm.registry import ModelInfo

_PACIFIC_STANDARD: Final = timedelta(hours=-8)
_MINUTE: Final = 60.0


def _now() -> datetime:
    return datetime.now(UTC)


class FreeTier:
    """Counts and paces every model's requests. With a `path`, the day's counts are kept in that
    file; without one, only for as long as this object lives, as in tests."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        share: float = 0.9,
        clock: Callable[[], datetime] = _now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._path = path
        self._share = share
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._at_once: dict[str, asyncio.Semaphore] = {}
        self._recent: dict[str, deque[float]] = {}
        self._state: dict[str, Any] = self._load()

    def _today(self) -> str:
        return (self._clock() + _PACIFIC_STANDARD).date().isoformat()

    def _load(self) -> dict[str, Any]:
        fresh: dict[str, Any] = {"day": self._today(), "requests": {}, "used_up": []}
        if self._path is None or not self._path.is_file():
            return fresh
        try:
            kept = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return fresh
        return kept if isinstance(kept, dict) and kept.get("day") == fresh["day"] else fresh

    async def _save(self) -> None:
        if self._path is None:
            return
        text = json.dumps(self._state, indent=2)
        path = self._path

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")

        await asyncio.to_thread(write)

    def _new_day(self) -> None:
        today = self._today()
        if self._state.get("day") != today:
            self._state = {"day": today, "requests": {}, "used_up": []}

    def daily_limit(self, info: ModelInfo) -> int:
        """How many requests v2 may make to the model today: its share of the free tier's."""
        return max(1, math.floor(info.per_day * self._share))

    def requests_today(self, model: str) -> int:
        """How many requests the model has had today."""
        self._new_day()
        return int(self._state["requests"].get(model, 0))

    async def _take_turn(self, info: ModelInfo) -> None:
        """Wait for room in the minute, and count the request. Raises BudgetUsedUp when the
        day's requests are used up."""
        while True:
            async with self._lock:
                self._new_day()
                if info.model in self._state["used_up"]:
                    raise BudgetUsedUp(f"{info.model}'s free quota is used up for today")
                used = self.requests_today(info.model)
                if used >= self.daily_limit(info):
                    raise BudgetUsedUp(
                        f"{info.model} has had its {self.daily_limit(info)} requests for today"
                    )
                recent = self._recent.setdefault(info.model, deque())
                now = time.monotonic()
                while recent and now - recent[0] >= _MINUTE:
                    recent.popleft()
                if len(recent) < info.per_minute:
                    recent.append(now)
                    self._state["requests"][info.model] = used + 1
                    await self._save()
                    return
                wait = _MINUTE - (now - recent[0]) + 0.05
            await self._sleep(wait)

    @asynccontextmanager
    async def turn(self, info: ModelInfo) -> AsyncIterator[None]:
        """Hold one of the model's places for a request: no more at once than it allows, no
        more in a minute, and none once the day's are used up."""
        at_once = self._at_once.setdefault(info.model, asyncio.Semaphore(info.at_once))
        async with at_once:
            await self._take_turn(info)
            yield

    async def used_up_for_today(self, model: str) -> None:
        """Record that the provider says the model's daily quota is used up."""
        async with self._lock:
            self._new_day()
            if model not in self._state["used_up"]:
                self._state["used_up"].append(model)
                await self._save()
