"""Tests for building the evaluation report."""

from decimal import Decimal
from pathlib import Path

import pytest

from bi2.evaluation.gold import GoldSet, GoldSite
from bi2.evaluation.report import build_report, load_results
from tests.factories import answered, site_result

GOLD = GoldSet(
    sites=(
        GoldSite(
            url="https://example-cafe.ca/",
            category="cafe",
            confirmed=True,
            company_names=("Example Cafe",),
        ),
        GoldSite(url="https://example-bar.ca/", category="bar", company_names=("Example Bar",)),
    )
)

STEP_COST = {"usd": "0.002", "input_tokens": 1000, "output_tokens": 50, "model_calls": 1}


def test_report_counts_verdicts_cost_and_time() -> None:
    report = build_report(GOLD, [site_result("https://www.example-cafe.ca", seconds=8.0)])
    names = next(summary for summary in report.fields if summary.field == "company_name")
    assert (names.scored, names.correct, names.missed) == (2, 0, 2)
    assert report.sites_run == 1
    assert report.seconds_per_site == 8.0
    assert report.unconfirmed_sites == 1


def test_report_adds_up_cost_from_every_step() -> None:
    name = answered("Example Cafe") | {
        "steps": [{"step": "llm", "outcome": "resolved", "cost": STEP_COST}]
    }
    report = build_report(GOLD, [site_result("https://example-cafe.ca/", company_name=name)])
    assert report.cost.usd == Decimal("0.002")
    assert report.cost_per_site == Decimal("0.002")
    names = next(summary for summary in report.fields if summary.field == "company_name")
    assert names.accuracy == 0.5


def test_confirmed_only_skips_unchecked_sites() -> None:
    report = build_report(GOLD, [], confirmed_only=True)
    assert [site.url for site in report.sites] == ["https://example-cafe.ca/"]


def test_two_results_for_one_site_are_rejected() -> None:
    results = [site_result("https://example-cafe.ca/"), site_result("http://www.example-cafe.ca")]
    with pytest.raises(ValueError, match="more than one result"):
        build_report(GOLD, results)


def test_load_results_reports_the_bad_line(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    path.write_text(site_result().model_dump_json() + "\n{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        load_results(path)
