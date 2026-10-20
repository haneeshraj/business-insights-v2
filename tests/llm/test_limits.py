"""Tests for keeping model calls under the free tiers' limits."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bi2.core.errors import BudgetUsedUp
from bi2.llm.limits import FreeTier
from bi2.llm.registry import ModelInfo

INFO = ModelInfo.model_validate(
    {
        "provider": "gemini",
        "model": "m",
        "input_per_million": 1,
        "output_per_million": 1,
        "per_minute": 2,
        "per_day": 4,
        "at_once": 1,
    }
)


async def test_a_full_minute_waits_and_a_full_day_refuses() -> None:
    waits: list[float] = []
    limits: FreeTier

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        limits._recent["m"].clear()  # the minute has passed

    limits = FreeTier(share=1.0, sleep=sleep)
    for _ in range(4):
        async with limits.turn(INFO):
            pass
    assert len(waits) == 1  # the third request waited for the next minute
    with pytest.raises(BudgetUsedUp):
        async with limits.turn(INFO):
            pass


def test_only_the_share_of_a_day_is_used() -> None:
    assert FreeTier(share=0.5).daily_limit(INFO) == 2


async def test_the_days_count_lasts_across_runs_and_resets_the_next_day(tmp_path: Path) -> None:
    now = datetime(2026, 10, 20, 18, tzinfo=UTC)
    path = tmp_path / "usage.json"
    async with FreeTier(path, share=1.0, clock=lambda: now).turn(INFO):
        pass
    assert FreeTier(path, clock=lambda: now).requests_today("m") == 1
    # Midnight Pacific standard time is 08:00 UTC.
    tomorrow = FreeTier(path, clock=lambda: now + timedelta(hours=14, minutes=1))
    assert tomorrow.requests_today("m") == 0


async def test_a_quota_the_provider_says_is_used_up_isnt_asked_again(tmp_path: Path) -> None:
    await FreeTier(tmp_path / "usage.json").used_up_for_today("m")
    with pytest.raises(BudgetUsedUp, match="used up"):
        async with FreeTier(tmp_path / "usage.json").turn(INFO):
            pass
