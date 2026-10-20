"""API keys in the operating system's keychain: Windows Credential Manager, macOS Keychain, or
Secret Service on Linux. Keys set in the environment always come first."""

from typing import Final, Literal

import keyring
from keyring.errors import KeyringError, NoKeyringError
from pydantic import SecretStr

from bi2.core.settings import Keys

Provider = Literal["gemini", "jev"]
PROVIDERS: Final[tuple[Provider, ...]] = ("gemini", "jev")
_SERVICE: Final = "bi2"


def keychain_key(provider: Provider) -> str | None:
    """The key saved in the keychain for a provider, or None."""
    try:
        return keyring.get_password(_SERVICE, provider)
    except (KeyringError, NoKeyringError):
        return None


def save_key(provider: Provider, key: str) -> None:
    """Save a provider's key in the keychain. Raises KeyringError when there's no keychain."""
    keyring.set_password(_SERVICE, provider, key)


def delete_key(provider: Provider) -> bool:
    """Remove a provider's key from the keychain; whether one was there."""
    try:
        keyring.delete_password(_SERVICE, provider)
    except (KeyringError, NoKeyringError):
        return False
    return True


def with_keychain(keys: Keys) -> tuple[Keys, dict[str, str]]:
    """The environment's keys, with the keychain's for any provider the environment lacks,
    and where each key was found."""
    found: dict[str, str] = {}
    update: dict[str, SecretStr] = {}
    for provider in PROVIDERS:
        if getattr(keys, provider) is not None:
            found[provider] = "environment"
        elif (saved := keychain_key(provider)) is not None:
            update[provider] = SecretStr(saved)
            found[provider] = "keychain"
    return keys.model_copy(update=update), found
