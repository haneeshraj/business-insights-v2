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
