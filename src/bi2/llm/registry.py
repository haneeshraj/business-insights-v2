"""The model registry, data/models.toml: each model's prices and limits.

A model the registry doesn't list can still be used, by its "provider:model" name: it gets no
price, so its calls count as free in the logs, and limits loose enough for a paid key. A config
file's [models."provider:model"] gives any model its own prices and limits.
"""

import tomllib
from collections.abc import Mapping
from decimal import Decimal
from functools import cache
from importlib.resources import files
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from bi2.core.models import Cost
from bi2.core.providers import ModelRef
from bi2.core.settings import ModelSettings

_MILLION: Final = Decimal(1_000_000)


class ModelInfo(BaseModel):
    """One model's list prices, in US dollars per million tokens, and the limits v2 keeps to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str
    input_per_million: Decimal = Field(default=Decimal(0), ge=0)
    output_per_million: Decimal = Field(default=Decimal(0), ge=0)
    per_minute: int = Field(ge=1)
    per_day: int = Field(ge=1)
    at_once: int = Field(default=2, ge=1)
    thinking: str | None = None  # how hard a reasoning model thinks, when it takes a level
    listed: bool = True  # in data/models.toml, so its prices are known

    @property
    def ref(self) -> ModelRef:
        return ModelRef(self.provider, self.model)

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
def _registry() -> dict[ModelRef, ModelInfo]:
    text = files("bi2.data").joinpath("models.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    return {
        ModelRef(provider, model): ModelInfo(provider=provider, model=model, **info)
        for provider, table in data.items()
        if isinstance(table, dict)
        for model, info in table.items()
    }


def listed_models(provider: str | None = None) -> list[ModelInfo]:
    """The models the registry lists, for one provider or all."""
    return [info for ref, info in _registry().items() if provider in (None, ref.provider)]


def model_info(
    model: str | ModelRef, overrides: Mapping[str, ModelSettings] | None = None
) -> ModelInfo:
    """A model's entry, with a config file's prices and limits for it laid over.

    By a bare name, the model must be listed: raises KeyError otherwise. By its ModelRef, an
    unlisted model gets no price and loose limits."""
    if isinstance(model, ModelRef):
        ref = model
        # A model the registry doesn't list: no known price, and a paid key's usual room.
        info = _registry().get(ref) or ModelInfo(
            provider=ref.provider,
            model=ref.model,
            per_minute=60,
            per_day=100_000,
            at_once=2,
            listed=False,
        )
    else:
        found = [info for key, info in _registry().items() if key.model == model]
        if not found:
            raise KeyError(f"{model} isn't in data/models.toml")
        info = found[0]
    change = (overrides or {}).get(str(info.ref)) or (overrides or {}).get(info.model)
    if change is not None:
        info = info.model_copy(update=change.model_dump(exclude_none=True))
    return info


def registry_version() -> str:
    """The models file's version, for results' version records."""
    text = files("bi2.data").joinpath("models.toml").read_text(encoding="utf-8")
    return str(tomllib.loads(text)["version"])
