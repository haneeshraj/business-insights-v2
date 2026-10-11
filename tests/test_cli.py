"""Smoke tests for the `bi2` command."""

from typer.testing import CliRunner

from bi2 import __version__
from bi2.cli.main import app

runner = CliRunner()


def test_version_flag_prints_the_installed_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"bi2 {__version__}"


def test_no_arguments_shows_the_help() -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output
