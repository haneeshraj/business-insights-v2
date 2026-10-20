"""The model registry, data/models.toml: each model's prices and free-tier limits."""

import tomllib
from decimal import Decimal
from functools import cache
from importlib.resources import files
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from bi2.core.models import Cost

Provider = Literal["jev", "gemini"]
_MILLION: Final = Decimal(1_000_000)


class ModelInfo(BaseModel):
    """One model's list prices, in US dollars per million tokens, and the limits v2 keeps to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Provider
    model: str
    input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(ge=0)
    per_minute: int = Field(ge=1)
    per_day: int = Field(ge=1)
    at_once: int = Field(default=2, ge=1)
    thinking: str | None = None  # Gemini's thinking level, when the model takes one

    def cost(self, input_tokens: int, output_tokens: int) -> Cost:
        """What a call with these token counts costs at list price."""
        usd = (
            self.input_per_million * input_tokens + self.output_per_million * output_tokens
        ) / _MILLION
        return Cost(
            usd=usd.quantize(Decimal("0.0000001")),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_calls=1,
        )


@cache
def _registry() -> dict[str, ModelInfo]:
    text = files("bi2.data").joinpath("models.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    found = {}
    for provider in ("jev", "gemini"):
        for model, info in data.get(provider, {}).items():
            found[model] = ModelInfo(provider=provider, model=model, **info)
    return found


def model_info(model: str) -> ModelInfo:
    """A model's entry. Raises KeyError for a model the registry doesn't list."""
    found = _registry().get(model)
    if found is None:
        raise KeyError(f"{model} isn't in data/models.toml")
    return found


def registry_version() -> str:
    """The models file's version, for results' version records."""
    text = files("bi2.data").joinpath("models.toml").read_text(encoding="utf-8")
    return str(tomllib.loads(text)["version"])
