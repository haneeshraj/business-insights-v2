"""Checks the repository's own gold file, so a bad edit fails in CI."""

from collections import Counter
from pathlib import Path

from bi2.core.models import PageKind
from bi2.evaluation.gold import load_gold_set

GOLD_FILE = Path(__file__).parents[2] / "eval" / "gold.toml"


def test_the_gold_file_loads() -> None:
    gold = load_gold_set(GOLD_FILE)
    assert len(gold.sites) >= 50


def test_the_gold_file_covers_more_than_food_and_drink() -> None:
    categories = Counter(site.category for site in load_gold_set(GOLD_FILE).sites)
    food_and_drink = sum(categories[name] for name in ("bar", "brewery", "cafe"))
    assert len(categories) >= 20
    assert food_and_drink < sum(categories.values()) / 2


def test_the_gold_file_includes_platform_pages() -> None:
    kinds = [site.page_kind for site in load_gold_set(GOLD_FILE).sites]
    assert PageKind.PLATFORM_PROFILE in kinds
