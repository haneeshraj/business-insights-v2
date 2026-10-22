"""Tests for keys from the environment and the system keychain."""

import pytest
from pydantic import SecretStr

from bi2.adapters.local import keys as keychain
from bi2.core.settings import Keys


def test_the_environment_comes_first_and_the_keychain_fills_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = {"jev": "jev-from-keychain", "gemini": "gemini-from-keychain"}
    monkeypatch.setattr(keychain, "keychain_key", lambda provider: saved.get(provider))
    keys, found = keychain.with_keychain(Keys(llm={"gemini": SecretStr("gemini-from-env")}))
    assert keys.gemini is not None
    assert keys.gemini.get_secret_value() == "gemini-from-env"
    assert keys.jev is not None
    assert keys.jev.get_secret_value() == "jev-from-keychain"
    assert found == {"gemini": "environment", "jev": "keychain"}


def test_blank_keys_count_as_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from bi2.core.settings import keys_from_environment

    monkeypatch.setenv("JEV_API_KEY", "  ")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert keys_from_environment().jev is None
