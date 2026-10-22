"""Building the client for a model: the one place that knows which client speaks which
provider's API. Entry points use it to run, to check a key, and to list a key's models."""

from types import TracebackType
from typing import Protocol, Self

from bi2.core.asking import Generated, Prompt
from bi2.core.providers import ModelRef, ProviderSettings
from bi2.core.settings import Settings
from bi2.llm.anthropic import Anthropic
from bi2.llm.gemini import Gemini
from bi2.llm.limits import FreeTier
from bi2.llm.openai_compatible import OpenAICompatible
from bi2.llm.registry import model_info


class ProviderClient(Protocol):
    """A model's client: it answers prompts, lists the key's models, and opens and closes its
    connections as an async context manager."""

    @property
    def name(self) -> str: ...

    async def generate(self, prompt: Prompt) -> Generated: ...

    async def models(self) -> list[str]: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


def client_for(
    ref: ModelRef,
    *,
    provider: ProviderSettings,
    key: str | None,
    settings: Settings,
    limits: FreeTier,
    backup: ModelRef | None = None,
) -> ProviderClient:
    """The client that asks a model on its provider. With `backup`, a Gemini client asks that
    model too when the first is busy or out of requests, sharing what it learns, like a refused
    web search."""
    ai = settings.ai
    if provider.api == "gemini":
        return Gemini(
            key or "",
            limits=limits,
            model=ref.model,
            backup=backup.model if backup else None,
            temperature=ai.temperature,
            timeout_s=ai.timeout_s,
            overrides=settings.models,
        )
    info = model_info(ref, settings.models)
    if provider.api == "anthropic":
        return Anthropic(
            key or "",
            provider=provider,
            info=info,
            limits=limits,
            name=ref.provider,
            temperature=ai.temperature,
            timeout_s=ai.timeout_s,
        )
    return OpenAICompatible(
        key,
        name=ref.provider,
        provider=provider,
        info=info,
        limits=limits,
        temperature=ai.temperature,
        timeout_s=ai.timeout_s,
    )
