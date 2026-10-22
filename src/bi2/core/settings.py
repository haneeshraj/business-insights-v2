"""The settings schema, and loading it. This is the only module that reads environment
variables.

Every setting has a default here. Settings come in layers, each overriding the ones before it:

1. the defaults below
2. the user's own config file, `bi2.toml` in v2's folder in the user's settings (on Windows,
   %APPDATA%/bi2), for every folder they run v2 in
3. this folder's `bi2.toml`, for a project, a team or CI; or the file BI2_CONFIG names
4. environment variables: BI2_ followed by the setting's path, with "__" between levels, like
   BI2_AI__LLM_MODEL=openai:gpt-5.4-mini or BI2_THRESHOLDS__ACCEPT=0.9
5. what a command is told, like `bi2 analyze --model ...`

API keys aren't settings: they're read from each provider's usual environment variable, like
OPENAI_API_KEY, by `keys_from_environment`, or from the system keychain, and never from a config
file, since config files get committed and shared.
"""

import os
import sys
import tomllib
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from bi2.core.models import Confidence
from bi2.core.providers import JEV, ModelRef, ProviderSettings, parse_model, providers

CONFIG_FILE: Final = "bi2.toml"


class Thresholds(BaseModel):
    """How sure an answer has to be."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accept: Confidence = 0.85  # needed to accept an answer; a field below it needs review


class AiSettings(BaseModel):
    """Which models answer what the rules aren't sure of, and how much they may be asked."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True  # BI2_AI__ENABLED=false makes every run rules-only, with no model calls
    # The LLM, as "provider:model", like "openai:gpt-5.4-mini" or "anthropic:claude-haiku-5-5";
    # a model data/models.toml lists can go by its name alone. The backup is asked when the
    # first is down, busy, or out of requests for the day; "" or "none" means none. Gemini's
    # free tier gives Flash 20 requests a day and Flash-Lite many more, so Flash-Lite is first.
    llm_model: str = "gemini-flash-lite-latest"
    backup_model: str = "gemini-3.5-flash"
    # The model web searches go to, for head offices no page gives; "" sends them to the LLM.
    # Only Gemini can search the web here, so with another provider's LLM, name a Gemini model.
    search_model: str = ""
    # Whether the LLM is asked at all. Without it, only Jev is: much faster on Gemini's free
    # tier, which takes 15 to 60 seconds a call, for a few more answers left to review.
    llm: bool = True
    temperature: float = Field(default=0.0, ge=0, le=2)  # 0 gives the same answer every time
    timeout_s: float = Field(default=90.0, gt=0)  # how long one model call may take
    # Whether Jev makes the typed choices when its key is set. Without it, the LLM does.
    jev: bool = True
    jev_model: str = "jev-latest"
    jev_images: bool = True  # whether Jev is shown screenshots, like the numbered logo boxes
    # Whether a site's questions for Jev that are asked at the same time go in one call.
    fan_out: bool = True
    # Whether a field the pages don't answer, like a chain's head-office address, may be looked
    # up with a web search, through Gemini's Google Search grounding.
    search: bool = True
    # The most model calls one site may make, so one strange site can't use up a day's budget.
    calls_per_site: int = Field(default=12, ge=0)
    # The share of each free tier's daily requests v2 may use, leaving the rest for the key's
    # other uses.
    daily_share: float = Field(default=0.9, gt=0, le=1)

    @field_validator("backup_model", "search_model")
    @classmethod
    def _none_means_empty(cls, name: str) -> str:
        # An empty environment variable counts as unset, so "none" is how one turns these off.
        return "" if name.strip().lower() == "none" else name


class ModelSettings(BaseModel):
    """A model's prices and limits, for one data/models.toml doesn't list or lists with a free
    tier's limits, like a paid key's higher ones. Unset ones keep the listed values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_per_million: Decimal | None = Field(default=None, ge=0)  # US dollars, at list price
    output_per_million: Decimal | None = Field(default=None, ge=0)
    per_minute: int | None = Field(default=None, ge=1)
    per_day: int | None = Field(default=None, ge=1)
    at_once: int | None = Field(default=None, ge=1)
    thinking: str | None = None  # how hard a reasoning model thinks, like "minimal" or "low"


def user_config_dir() -> Path:
    """v2's folder in the user's settings: the same one `typer.get_app_dir("bi2")` gives."""
    system = str(sys.platform)  # a plain str, so the type checker keeps every branch
    if system == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "bi2"
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "bi2"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "bi2"


def user_config_file() -> Path:
    """The user's own config file, read in every folder."""
    return user_config_dir() / CONFIG_FILE


def project_config_file() -> Path:
    """The project's config file: the one BI2_CONFIG names, or else this folder's bi2.toml."""
    named = os.environ.get("BI2_CONFIG", "").strip()
    return Path(named) if named else Path.cwd() / CONFIG_FILE


def config_files() -> list[Path]:
    """The config files a run reads, the one that wins first."""
    return [project_config_file(), user_config_file()]


class Settings(BaseSettings):
    """Every setting a run uses."""

    model_config = SettingsConfigDict(
        env_prefix="BI2_",
        env_nested_delimiter="__",
        env_ignore_empty=True,  # an empty variable, like an unset CI input, counts as unset
        frozen=True,
        extra="forbid",
    )

    thresholds: Thresholds = Thresholds()
    ai: AiSettings = AiSettings()
    # Providers to add, or to change field by field, like a server's address: see
    # data/providers.toml for the fields.
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Prices and limits for models, by "provider:model".
    models: dict[str, ModelSettings] = Field(default_factory=dict)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """What a command is told first, then the environment, then the config files."""
        found = [
            TomlConfigSettingsSource(settings_cls, toml_file=path)
            for path in config_files()
            if path.is_file()
        ]
        return (init_settings, env_settings, *found)

    def all_providers(self) -> dict[str, ProviderSettings]:
        """Every provider: the built-in ones, with this run's additions and changes."""
        return providers(self.providers)

    def llm_models(self) -> dict[str, ModelRef]:
        """The LLMs these settings name, by setting: llm_model, backup_model and search_model,
        the ones set. Raises ValueError, saying which setting and how to name it, for a model
        whose provider can't be told, or for Jev's, since Jev isn't an LLM."""
        known = self.all_providers()
        found = {}
        for setting in ("llm_model", "backup_model", "search_model"):
            name = getattr(self.ai, setting)
            if not name:
                continue
            try:
                ref = parse_model(name, known)
            except ValueError as exc:
                raise ValueError(f"ai.{setting}: {exc}") from None
            if ref.provider == JEV:
                raise ValueError(f"ai.{setting} is {ref}, which is Jev, the Decider, not an LLM")
            found[setting] = ref
        return found


def _from_file(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _has(data: Mapping[str, Any], parts: tuple[str, ...]) -> bool:
    for part in parts:
        if not isinstance(data, Mapping) or part not in data:
            return False
        data = data[part]
    return True


def where_set(settings: "Settings") -> list[tuple[str, str, str]]:
    """Each run setting, its value, and where it came from: an environment variable, this
    folder's config file, the user's, or the default. Settings a command is told aren't known
    here."""
    project, user = _from_file(project_config_file()), _from_file(user_config_file())
    found = []
    for section in ("ai", "thresholds"):
        values = getattr(settings, section).model_dump()
        for name, value in values.items():
            variable = f"BI2_{section}__{name}".upper()
            if os.environ.get(variable, "").strip():
                source = f"environment ({variable})"
            elif _has(project, (section, name)):
                source = f"this folder's file ({project_config_file().name})"
            elif _has(user, (section, name)):
                source = "your config file"
            else:
                source = "default"
            found.append((f"{section}.{name}", str(value), source))
    return found


class Keys(BaseModel):
    """API keys: Jev's, and each LLM provider's by its name. `Keys(gemini=..., openai=...)`
    works too."""

    model_config = ConfigDict(frozen=True)

    jev: SecretStr | None = None
    llm: dict[str, SecretStr] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _by_provider(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        llm = dict(data.get("llm") or {})
        llm |= {
            name: value
            for name, value in data.items()
            if name not in ("jev", "llm") and value is not None
        }
        return {"jev": data.get("jev"), "llm": llm}

    @property
    def gemini(self) -> SecretStr | None:
        return self.llm.get("gemini")

    def get(self, provider: str) -> SecretStr | None:
        """A provider's key, or None."""
        return self.jev if provider == JEV else self.llm.get(provider)

    def with_key(self, provider: str, key: SecretStr) -> "Keys":
        """These keys and one more."""
        if provider == JEV:
            return self.model_copy(update={"jev": key})
        return self.model_copy(update={"llm": {**self.llm, provider: key}})


def _first_set(names: tuple[str, ...]) -> SecretStr | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return SecretStr(value)
    return None


def keys_from_environment(known: Mapping[str, ProviderSettings] | None = None) -> Keys:
    """The keys set in the environment, under each provider's usual names. A key that's set but
    empty counts as not set."""
    known = known if known is not None else providers()
    llm = {name: key for name, provider in known.items() if (key := _first_set(provider.keys))}
    return Keys(jev=_first_set(("JEV_API_KEY", "TYPESAFE_API_KEY")), llm=llm)
