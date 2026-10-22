"""The LLM providers v2 can call, and naming a model on one.

A model is named "provider:model", like "openai:gpt-5.4-mini" or "ollama:llama3.1:8b". A model
data/models.toml lists can go by its name alone, like "gemini-flash-lite-latest", and so can one
whose name says whose it is, the way v1 told them apart: "gpt-" and "o3" are OpenAI's, "claude-"
Anthropic's, "gemini-" Google's, "mistral-" Mistral's, and so on.

The providers come from data/providers.toml, with any a config file adds or changes.
"""

import re
import tomllib
from collections.abc import Mapping
from functools import cache
from importlib.resources import files
from typing import Any, Final, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

Api = Literal["openai", "anthropic", "gemini"]
JsonMode = Literal["schema", "object", "text"]

JEV: Final = "jev"  # the Decider's provider, which isn't an LLM provider


class ProviderSettings(BaseModel):
    """One LLM provider: which API it speaks, where it is, and where its key may be."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    title: str = ""  # its name for people, like "OpenAI"
    api: Api = "openai"  # most providers speak OpenAI's chat completions API
    base_url: str = ""
    keys: tuple[str, ...] = ()  # environment variables its key may be in, in order
    needs_key: bool = True  # false for servers that take none, like a local Ollama
    local: bool = False  # runs on the user's own machine
    # How it's first asked for JSON; "json" in providers.toml and bi2.toml.
    json_mode: JsonMode = Field(default="schema", alias="json")
    token_param: str = "max_tokens"  # the request field for the most output tokens
    models: tuple[str, ...] = ()  # models to suggest when choosing one


class ModelRef(NamedTuple):
    """A model on a provider."""

    provider: str
    model: str

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


@cache
def _built_in() -> dict[str, dict[str, Any]]:
    text = files("bi2.data").joinpath("providers.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    return {name: table for name, table in data.items() if isinstance(table, dict)}


@cache
def _listed() -> dict[str, str]:
    """The models data/models.toml lists, with their providers."""
    text = files("bi2.data").joinpath("models.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    return {
        model: provider
        for provider, table in data.items()
        if isinstance(table, dict)
        for model in table
    }


def providers(
    changes: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, ProviderSettings]:
    """Every provider, by name: the built-in ones, with a config file's additions and changes
    laid over them field by field."""
    merged: dict[str, dict[str, Any]] = {name: dict(table) for name, table in _built_in().items()}
    for name, change in (changes or {}).items():
        merged[name] = {**merged.get(name, {}), **change}
    return {name: ProviderSettings(**table) for name, table in merged.items()}


# What a model's name says about whose it is, when it's given without its provider.
_NAMED: Final[tuple[tuple[str, str], ...]] = (
    (r"(gpt-|chatgpt-|o\d)", "openai"),
    (r"claude-", "anthropic"),
    (r"(gemini-|gemma-)", "gemini"),
    (r"(mistral-|ministral-|magistral-|codestral-|devstral-|pixtral-|open-mistral)", "mistral"),
    (r"grok-", "xai"),
    (r"deepseek-", "deepseek"),
    (r"command-", "cohere"),
    (r"sonar", "perplexity"),
    (r"jev-", JEV),
)


def parse_model(name: str, known: Mapping[str, ProviderSettings] | None = None) -> ModelRef:
    """The provider and model a model's name means. Raises ValueError, saying how to name it,
    when the provider can't be told."""
    known = known if known is not None else providers()
    name = name.strip()
    if not name:
        raise ValueError("no model was named")
    provider, _, model = name.partition(":")
    if model and (provider in known or provider == JEV):
        return ModelRef(provider, model)
    if (listed := _listed().get(name)) is not None:
        return ModelRef(listed, name)
    for pattern, owner in _NAMED:
        if re.match(pattern, name, flags=re.IGNORECASE):
            return ModelRef(owner, name)
    choices = ", ".join(sorted(known))
    raise ValueError(
        f'"{name}" doesn\'t say whose model it is: name it as "provider:model", like '
        f'"openai:gpt-5.4-mini" or "ollama:{name}". The providers: {choices}'
    )
