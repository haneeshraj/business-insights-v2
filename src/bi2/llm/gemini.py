"""Gemini, through its generateContent REST API, as v2's LanguageModel.

Answers are JSON of the shape each prompt asks for, which Gemini enforces with a response
schema. Each request first takes a turn from the free tier's limits. A busy model is asked again
after a pause, and then the backup model is asked instead; so is one whose free quota is used up
for the day.
"""

import asyncio
import base64
import json
import re
from types import TracebackType
from typing import Any, Final, Self

import httpx

from bi2.core.asking import Generated, Prompt
from bi2.core.errors import BudgetUsedUp, ModelUnavailable
from bi2.llm.limits import FreeTier
from bi2.llm.registry import ModelInfo, model_info

_API: Final = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_BUSY: Final = frozenset({500, 502, 503, 504})
_TRIES: Final = 3
_LONGEST_WAIT_S: Final = 60.0


def media_type(image: bytes) -> str:
    """An image's media type, from its first bytes: PNG or JPEG, the two every model takes."""
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image.startswith(b"\xff\xd8"):
        return "image/jpeg"
    raise ValueError("only PNG and JPEG images can be sent to a model")


def _body(prompt: Prompt, info: ModelInfo) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"text": prompt.evidence}]
    parts += [
        {"inline_data": {"mime_type": media_type(image), "data": base64.b64encode(image).decode()}}
        for image in prompt.images
    ]
    config: dict[str, Any] = {
        "temperature": 0,
        "maxOutputTokens": prompt.max_output_tokens,
        "responseMimeType": "application/json",
        "responseJsonSchema": prompt.answer_schema,
    }
    if info.thinking:
        config["thinkingConfig"] = {"thinkingLevel": info.thinking}
    return {
        "systemInstruction": {"parts": [{"text": prompt.instructions}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": config,
    }


def _retry_delay(error: dict[str, Any]) -> float | None:
    """How long Google asks callers to wait, from its RetryInfo detail, like "32s"."""
    for detail in error.get("details", []):
        delay = str(detail.get("retryDelay", ""))
        if match := re.fullmatch(r"(\d+(?:\.\d+)?)s", delay):
            return float(match[1])
    return None


def _daily_quota(error: dict[str, Any]) -> bool:
    """Whether a refusal is for the day's quota, rather than the minute's."""
    return any(
        "PerDay" in str(violation.get("quotaId", ""))
        for detail in error.get("details", [])
        for violation in detail.get("violations", [])
    )


def _answer(data: dict[str, Any], model: str) -> tuple[dict[str, Any], str]:
    """The JSON answer in a response, and the model version that gave it."""
    candidates = data.get("candidates") or []
    if not candidates:
        reason = data.get("promptFeedback", {}).get("blockReason", "no answer")
        raise ModelUnavailable(f"{model} gave no answer ({reason})")
    candidate = candidates[0]
    finish = candidate.get("finishReason", "STOP")
    if finish != "STOP":
        raise ModelUnavailable(f"{model} stopped before finishing its answer ({finish})")
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
    try:
        answer = json.loads(text)
    except ValueError as exc:
        raise ModelUnavailable(f"{model}'s answer wasn't JSON") from exc
    if not isinstance(answer, dict):
        raise ModelUnavailable(f"{model}'s answer wasn't a JSON object")
    return answer, str(data.get("modelVersion", model))


class Gemini:
    """Asks Gemini, its primary model first and then its backup."""

    name = "gemini"

    def __init__(
        self,
        key: str,
        *,
        limits: FreeTier,
        model: str = "gemini-3.5-flash",
        backup: str | None = "gemini-flash-lite-latest",
        timeout_s: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = key
        self._limits = limits
        self._models = [model_info(model)] + ([model_info(backup)] if backup else [])
        self._timeout_s = timeout_s
        self._transport = transport  # for tests, which answer without the network
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(timeout=self._timeout_s, transport=self._transport)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._client:
            await self._client.aclose()

    async def generate(self, prompt: Prompt) -> Generated:
        """The first model's answer that comes. Raises ModelUnavailable when none answers, and
        BudgetUsedUp when that's because every model's free quota is used up."""
        problems: list[ModelUnavailable] = []
        for info in self._models:
            try:
                return await self._ask(info, prompt)
            except ModelUnavailable as exc:
                problems.append(exc)
        why = "; ".join(str(problem) for problem in problems)
        if all(isinstance(problem, BudgetUsedUp) for problem in problems):
            raise BudgetUsedUp(why)
        raise ModelUnavailable(why)

    async def _ask(self, info: ModelInfo, prompt: Prompt) -> Generated:
        """One model's answer, asked again after a pause while it's busy. Every request takes
        its own turn from the free tier's limits."""
        if self._client is None:
            raise RuntimeError("use Gemini inside an `async with` block")
        body = _body(prompt, info)
        url = _API.format(model=info.model)
        for attempt in range(_TRIES):
            last = attempt + 1 == _TRIES
            async with self._limits.turn(info):
                try:
                    response = await self._client.post(
                        url, json=body, headers={"x-goog-api-key": self._key}
                    )
                except httpx.HTTPError as exc:
                    if last:
                        raise ModelUnavailable(f"{info.model} couldn't be reached: {exc}") from exc
                    response = None
            if response is None:
                await asyncio.sleep(2.0 * 2**attempt)
                continue
            if response.status_code == 200:
                return self._generated(response, info)
            error = _error(response)
            if response.status_code == 429 and _daily_quota(error):
                await self._limits.used_up_for_today(info.model)
                raise BudgetUsedUp(f"{info.model}'s free quota is used up for today")
            if response.status_code not in _BUSY | {429} or last:
                message = str(error.get("message", ""))[:200]
                raise ModelUnavailable(f"{info.model} answered {response.status_code}: {message}")
            wait = _retry_delay(error) or 2.0 * 2**attempt
            await asyncio.sleep(min(wait, _LONGEST_WAIT_S))
        raise ModelUnavailable(f"{info.model} didn't answer")  # pragma: no cover

    def _generated(self, response: httpx.Response, info: ModelInfo) -> Generated:
        try:
            data = response.json()
        except ValueError as exc:
            raise ModelUnavailable(f"{info.model}'s response wasn't JSON") from exc
        answer, version = _answer(data, info.model)
        usage = data.get("usageMetadata", {})
        output = int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0))
        cost = info.cost(int(usage.get("promptTokenCount", 0)), output)
        return Generated(data=answer, model=version, cost=cost)


def _error(response: httpx.Response) -> dict[str, Any]:
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        return {}
    return error if isinstance(error, dict) else {}
