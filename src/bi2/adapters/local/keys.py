"""API keys in the operating system's keychain: Windows Credential Manager, macOS Keychain, or
Secret Service on Linux. Keys set in the environment always come first."""

from collections.abc import Mapping
from typing import Final

import keyring
from keyring.errors import KeyringError, NoKeyringError
from pydantic import SecretStr

from bi2.core.providers import JEV, ProviderSettings, providers
from bi2.core.settings import Keys

_SERVICE: Final = "bi2"


def provider_names(known: Mapping[str, ProviderSettings] | None = None) -> tuple[str, ...]:
    """Every provider a key can be saved for: Jev, then each LLM provider."""
    return (JEV, *(known if known is not None else providers()))


def keychain_key(provider: str) -> str | None:
    """The key saved in the keychain for a provider, or None."""
    try:
        return keyring.get_password(_SERVICE, provider)
    except (KeyringError, NoKeyringError):
        return None


def save_key(provider: str, key: str) -> None:
    """Save a provider's key in the keychain. Raises KeyringError when there's no keychain."""
    keyring.set_password(_SERVICE, provider, key)


def delete_key(provider: str) -> bool:
    """Remove a provider's key from the keychain; whether one was there."""
    try:
        keyring.delete_password(_SERVICE, provider)
    except (KeyringError, NoKeyringError):
        return False
    return True


def with_keychain(
    keys: Keys, known: Mapping[str, ProviderSettings] | None = None
) -> tuple[Keys, dict[str, str]]:
    """The environment's keys, with the keychain's for any provider the environment lacks,
    and where each key was found."""
    found: dict[str, str] = {}
    for name in provider_names(known):
        if keys.get(name) is not None:
            found[name] = "environment"
        elif (saved := keychain_key(name)) is not None:
            keys = keys.with_key(name, SecretStr(saved))
            found[name] = "keychain"
    return keys, found
