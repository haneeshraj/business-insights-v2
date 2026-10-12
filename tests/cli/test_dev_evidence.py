"""Tests for `bi2 dev evidence`."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from bi2.cli.dev.saved import save_snapshot
from bi2.cli.main import app
from bi2.fetch.browser import BrowserName
from tests.factories import page_snapshot

runner = CliRunner()

CAFE = """<html><head><title>Example Cafe | Toronto</title>
<meta property="og:site_name" content="Example Cafe"></head><body>Coffee</body></html>"""


def test_saved_pages_are_checked_against_the_gold_set(tmp_path: Path) -> None:
    saved = tmp_path / "saved"
    save_snapshot(page_snapshot(CAFE), saved)
    gold = tmp_path / "gold.toml"
    gold.write_text(
        '[[site]]\nurl = "https://example-cafe.ca/"\ncategory = "cafe"\n'
        'company_names = ["Example Cafe"]\n',
        encoding="utf-8",
    )
    out = tmp_path / "out"
    outcome = runner.invoke(
        app, ["dev", "evidence", "--saved", str(saved), "--gold", str(gold), "--out", str(out)]
    )
    assert outcome.exit_code == 0, outcome.output
    assert "company_name" in outcome.output
    assert "1 of 1" in outcome.output
    assert (out / "example-cafe.ca" / "evidence.json").exists()
    assert (out / "coverage.json").exists()


@pytest.mark.browser
def test_evidence_for_a_live_page(tmp_path: Path, site: str, browser: BrowserName) -> None:
    outcome = runner.invoke(
        app,
        [
            "dev",
            "evidence",
            f"{site}/cafe",
            "--out",
            str(tmp_path),
            "--browser",
            browser,
            "--allow-private",
        ],
    )
    assert outcome.exit_code == 0, outcome.output
    assert "Example Cafe" in outcome.output
    saved = next(tmp_path.glob("*/evidence.json")).parent
    assert (saved / "page.html").exists()  # saved too, so it can be tried again with --saved


def test_evidence_needs_a_url_or_saved_pages(tmp_path: Path) -> None:
    neither = runner.invoke(app, ["dev", "evidence"])
    assert neither.exit_code == 2
    assert "either a URL or --saved" in neither.output
    gold = tmp_path / "gold.toml"
    gold.write_text("", encoding="utf-8")
    gold_alone = runner.invoke(app, ["dev", "evidence", "https://example.com", "--gold", str(gold)])
    assert gold_alone.exit_code == 2
    assert "--gold needs --saved" in gold_alone.output
