"""Tests for `bi2 dev fetch`, against the local test website."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from bi2.cli.main import app
from bi2.fetch.browser import BrowserName

pytestmark = pytest.mark.browser
runner = CliRunner()


def test_fetch_shows_and_saves_what_the_browser_captured(
    tmp_path: Path, site: str, browser: BrowserName
) -> None:
    outcome = runner.invoke(
        app,
        [
            "dev",
            "fetch",
            f"{site}/cafe",
            "--out",
            str(tmp_path),
            "--browser",
            browser,
            "--allow-private",
        ],
    )
    assert outcome.exit_code == 0, outcome.output
    assert "Images that could be the logo" in outcome.output
    saved = next(tmp_path.glob("*/screenshot.jpg")).parent
    assert "Example Cafe" in (saved / "page.html").read_text(encoding="utf-8")
    assert (saved / "snapshot.json").exists()


def test_fetch_refuses_private_addresses(tmp_path: Path, site: str, browser: BrowserName) -> None:
    outcome = runner.invoke(
        app, ["dev", "fetch", f"{site}/cafe", "--out", str(tmp_path), "--browser", browser]
    )
    assert outcome.exit_code == 1
    assert "isn't on the public internet" in outcome.output


def test_fetch_gold_reports_every_site(tmp_path: Path, site: str, browser: BrowserName) -> None:
    gold = tmp_path / "gold.toml"
    gold.write_text(
        f'[[site]]\nurl = "{site}/cafe"\ncategory = "cafe"\n\n'
        f'[[site]]\nurl = "{site}/slow"\ncategory = "cafe"\n',
        encoding="utf-8",
    )
    outcome = runner.invoke(
        app,
        [
            "dev",
            "fetch",
            "--gold",
            str(gold),
            "--out",
            str(tmp_path / "out"),
            "--browser",
            browser,
            "--timeout",
            "1",
            "--allow-private",
        ],
    )
    assert outcome.exit_code == 0, outcome.output
    assert "1 loaded" in outcome.output
    assert "1 timed out" in outcome.output
    assert (tmp_path / "out" / "summary.json").exists()


def test_fetch_needs_a_url_or_a_gold_file() -> None:
    outcome = runner.invoke(app, ["dev", "fetch"])
    assert outcome.exit_code == 2
    assert "either a URL or --gold" in outcome.output
