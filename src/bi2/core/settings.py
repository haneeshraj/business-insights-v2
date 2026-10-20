"""The settings schema, and loading it. This is the only module that reads environment
variables.

Every setting has a default here. An environment variable overrides it: BI2_ followed by the
setting's path, with "__" between levels, like BI2_THRESHOLDS__ACCEPT=0.9. Config files and
profiles come later (see docs/codebase.md, "Configuration").

API keys aren't settings: they're read from each provider's usual environment variable, by
`keys_from_environment`, and never from a config file.
"""

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from bi2.core.models import Confidence


class Thresholds(BaseModel):
    """How sure an answer has to be."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accept: Confidence = 0.85  # needed to accept an answer; a field below it needs review


class AiSettings(BaseModel):
    """Which models answer what the rules aren't sure of, and how much they may be asked."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True  # BI2_AI__ENABLED=false makes every run rules-only, with no model calls
    jev_model: str = "jev-latest"
    # Gemini models, by their IDs in data/models.toml: the one asked first, and the one asked
    # when it's busy or its free tier is used up for the day.
    llm_model: str = "gemini-3.5-flash"
    backup_model: str = "gemini-flash-lite-latest"
    jev_images: bool = True  # whether Jev is shown screenshots, like the numbered logo boxes
    # The most model calls one site may make, so one strange site can't use up a day's budget.
    calls_per_site: int = Field(default=12, ge=0)
    # The share of each free tier's daily requests v2 may use, leaving the rest for the key's
    # other uses.
    daily_share: float = Field(default=0.9, gt=0, le=1)


class Settings(BaseSettings):
    """Every setting a run uses."""

    model_config = SettingsConfigDict(
        env_prefix="BI2_", env_nested_delimiter="__", frozen=True, extra="forbid"
    )

    thresholds: Thresholds = Thresholds()
    ai: AiSettings = AiSettings()


class Keys(BaseSettings):
    """The API keys found in the environment, under each provider's usual names."""

    model_config = SettingsConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    gemini: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY")
    )
    jev: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("JEV_API_KEY", "TYPESAFE_API_KEY")
    )


def keys_from_environment() -> Keys:
    """The keys set in the environment. A key that's set but empty counts as not set."""
    keys = Keys()
    blank = {
        name
        for name in ("gemini", "jev")
        if (key := getattr(keys, name)) is not None and not key.get_secret_value().strip()
    }
    return keys.model_copy(update=dict.fromkeys(blank)) if blank else keys
