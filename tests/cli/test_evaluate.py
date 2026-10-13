"""Tests for the `bi2 eval score` command."""

import json
from pathlib import Path

from typer.testing import CliRunner

from bi2.cli.main import app
from tests.factories import answered, site_result

GOLD = """
[[site]]
url = "https://example-cafe.ca/"
category = "cafe"
company_names = ["Example Cafe"]
mcc_codes = ["5814"]
"""

runner = CliRunner()


def test_score_prints_accuracy_and_saves_the_report(tmp_path: Path) -> None:
    gold = tmp_path / "gold.toml"
    gold.write_text(GOLD, encoding="utf-8")
    results = tmp_path / "results.jsonl"
    result = site_result(company_name=answered("Example Cafe"))
    results.write_text(result.model_dump_json() + "\n", encoding="utf-8")
    report_file = tmp_path / "report.json"

    outcome = runner.invoke(
        app, ["eval", "score", str(gold), str(results), "--json", str(report_file)]
    )

    assert outcome.exit_code == 0, outcome.output
    assert "Accuracy by field" in outcome.output
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["sites_run"] == 1


def test_score_explains_a_broken_gold_file(tmp_path: Path) -> None:
    gold = tmp_path / "gold.toml"
    gold.write_text('[[site]]\nurl = "not a url"\ncategory = "cafe"\n', encoding="utf-8")
    results = tmp_path / "results.jsonl"
    results.write_text("", encoding="utf-8")

    outcome = runner.invoke(app, ["eval", "score", str(gold), str(results)])

    assert outcome.exit_code == 1
    assert "http or https URL" in outcome.output


def test_compare_lists_what_got_worse_and_says_so_in_its_exit_code(tmp_path: Path) -> None:
    gold = tmp_path / "gold.toml"
    gold.write_text(GOLD, encoding="utf-8")
    before = tmp_path / "before.jsonl"
    right = site_result(company_name=answered("Example Cafe")).model_dump_json() + "\n"
    before.write_text(right, encoding="utf-8")
    after = tmp_path / "after"  # a results folder, as bi2 analyze leaves it
    after.mkdir()
    worse = site_result(company_name=answered("Someone Else")).model_dump_json() + "\n"
    (after / "results.jsonl").write_text(worse, encoding="utf-8")
    checks = ["--gold", str(gold), "--checks", str(tmp_path / "no-checks.jsonl")]

    outcome = runner.invoke(app, ["eval", "compare", str(before), str(after), *checks])
    assert outcome.exit_code == 1
    assert "Answers that got worse" in outcome.output
    unchanged = runner.invoke(app, ["eval", "compare", str(before), str(before), *checks])
    assert unchanged.exit_code == 0
    assert "No answers changed." in unchanged.output
