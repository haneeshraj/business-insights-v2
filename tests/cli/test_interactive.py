"""Tests for the interactive session's commands, shown with Rich's recording console."""

from pathlib import Path

from rich.console import Console

from bi2.cli.interactive.commands import COMMANDS, export
from tests.factories import answered, site_result

URL = "https://www.bellwoodsbrewery.com/"


def _shown(renderable: object) -> str:
    console = Console(record=True, width=200)
    console.print(renderable)
    return console.export_text()


def _results() -> dict[str, object]:
    result = site_result(
        URL,
        company_name=answered("Bellwoods Brewery"),
        mcc=answered({"code": "5813", "description": "Drinking Places"}),
    )
    return {URL: result}


def test_show_finds_a_site_by_its_domain() -> None:
    shown = _shown(COMMANDS["/show"](_results(), ["bellwoodsbrewery.com"]))  # type: ignore[arg-type]
    assert "Bellwoods Brewery" in shown
    assert "5813 Drinking Places" in shown


def test_why_shows_a_fields_steps_and_says_how_to_ask() -> None:
    assert "Like: /why" in _shown(COMMANDS["/why"](_results(), ["bellwoodsbrewery.com"]))  # type: ignore[arg-type]
    unknown = _shown(COMMANDS["/show"]({}, ["example.com"]))
    assert "hasn't been analyzed" in unknown


def test_export_saves_the_sessions_results(tmp_path: Path) -> None:
    said = _shown(export(_results(), ["csv"], folder=tmp_path))  # type: ignore[arg-type]
    assert "Saved 1 results" in said
    assert (tmp_path / "results.csv").read_text(encoding="utf-8").startswith("url,")
