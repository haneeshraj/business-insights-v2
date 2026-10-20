"""Tests for `bi2 keys`, with the system keychain stood in for."""

import pytest
from typer.testing import CliRunner

from bi2.adapters.local import keys as keychain
from bi2.cli.main import app

runner = CliRunner()


@pytest.fixture
def saved(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A keychain in memory, and no keys in the environment."""
    store: dict[str, str] = {}
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "JEV_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(keychain, "keychain_key", lambda provider: store.get(provider))
    monkeypatch.setattr(
        "bi2.cli.doctor.save_key", lambda provider, key: store.__setitem__(provider, key)
    )
    return store


def test_a_saved_key_is_shown_by_its_last_four_characters_only(saved: dict[str, str]) -> None:
    result = runner.invoke(app, ["keys", "set", "jev"], input="tsk-1234567890abcd\n")
    assert result.exit_code == 0
    assert "1234567890" not in result.output
    shown = runner.invoke(app, ["keys", "show"])
    assert "jev: ...abcd, from the keychain" in shown.output
    assert "gemini: not set" in shown.output


def test_a_key_in_the_environment_comes_first(
    saved: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    saved["gemini"] = "from-keychain-0000"
    monkeypatch.setenv("GEMINI_API_KEY", "from-environment-9999")
    shown = runner.invoke(app, ["keys", "show"])
    assert "gemini: ...9999, from the environment" in shown.output
