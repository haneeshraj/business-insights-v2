"""Anthropic's Claude, through its Messages API, as v2's LanguageModel.

The answer's JSON schema is given as the one tool Claude is made to call, so its answer is that
call's input, in the shape the schema asks for. Each request first takes a turn from the model's
limits, and a busy or overloaded API is asked again after a pause.
"""

import asyncio
import base64
from types import TracebackType
from typing import Any, Final, Self

import httpx

from bi2.core.asking import Generated, Prompt
from bi2.core.errors import BudgetUsedUp, ModelUnavailable
from bi2.core.providers import ProviderSettings
from bi2.llm.common import BUSY, TRIES, error_message, json_answer, media_type, retry_after
from bi2.llm.limits import FreeTier
from bi2.llm.registry import ModelInfo

_VERSION: Final = "2023-06-01"
_TOOL: Final = "answer"
_LEAST_OUTPUT: Final = 1024
_USED_UP: Final = ("credit balance", "billing", "quota")


class Anthropic:
    """Asks one Claude model."""

    def __init__(
        self,
        key: str,
        *,
        provider: ProviderSettings,
        info: ModelInfo,
        limits: FreeTier,
        name: str = "anthropic",
        temperature: float = 0.0,
        timeout_s: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self._key = key
        self._url = provider.base_url.rstrip("/")
        self._info = info
        self._limits = limits
        self._temperature = temperature
        self._timeout_s = timeout_s
        self._transport = transport  # for tests, which answer without the network
        self._client: httpx.AsyncClient | None = None
        self._refused: set[str] = set()  # request fields this model refused

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

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._key, "anthropic-version": _VERSION}

    def _body(self, prompt: Prompt) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt.evidence}]
        for image in prompt.images:
            data = base64.b64encode(image).decode()
            source = {"type": "base64", "media_type": media_type(image), "data": data}
            content.append({"type": "image", "source": source})
        tool = {
            "name": _TOOL,
            "description": "Give the answer, in the shape asked for.",
            "input_schema": prompt.answer_schema,
        }
        body: dict[str, Any] = {
            "model": self._info.model,
            "max_tokens": max(prompt.max_output_tokens, _LEAST_OUTPUT),
            "system": prompt.instructions,
            "messages": [{"role": "user", "content": content}],
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": _TOOL},
        }
        if "temperature" not in self._refused:
            body["temperature"] = self._temperature
        return body

    async def generate(self, prompt: Prompt) -> Generated:
        """Claude's answer. Raises ModelUnavailable when it can't answer, and BudgetUsedUp when
        that's because the account's credit is used up."""
        if prompt.search:
            raise ModelUnavailable(
                f"{self.name} can't search the web here: web search needs a Gemini model,"
                " set as ai.search_model"
            )
        if self._client is None:
            raise RuntimeError("use the model inside an `async with` block")
        url = f"{self._url}/messages"
        attempt = 0
        while True:
            body = self._body(prompt)
            async with self._limits.turn(self._info):
                try:
                    response: httpx.Response | None = await self._client.post(
                        url, json=body, headers=self._headers()
                    )
                except httpx.HTTPError as exc:
                    response, problem = None, exc
            if response is None:
                attempt += 1
                if attempt >= TRIES:
                    raise ModelUnavailable(f"{self.name} couldn't be reached: {problem}")
                await asyncio.sleep(2.0 * 2.0**attempt)
                continue
            if response.status_code == 200:
                return self._generated(response)
            message = error_message(response)
            said = message.lower()
            if response.status_code == 400 and "temperature" in said and "temperature" in body:
                self._refused.add("temperature")
                continue
            if response.status_code in (400, 402, 429) and any(word in said for word in _USED_UP):
                raise BudgetUsedUp(f"{self.name}: {message}")
            if response.status_code in (401, 403):
                raise ModelUnavailable(
                    f"{self.name} refused the key ({response.status_code}): {message}"
                )
            attempt += 1
            if response.status_code not in BUSY | {429} or attempt >= TRIES:
                raise ModelUnavailable(
                    f"{self._info.model} answered {response.status_code}: {message}"
                )
            await asyncio.sleep(retry_after(response, attempt))

    def _generated(self, response: httpx.Response) -> Generated:
        model = self._info.model
        try:
            data = response.json()
        except ValueError as exc:
            raise ModelUnavailable(f"{model}'s response wasn't JSON") from exc
        blocks = [block for block in data.get("content") or [] if isinstance(block, dict)]
        called = next(
            (
                block["input"]
                for block in blocks
                if block.get("type") == "tool_use"
                and block.get("name") == _TOOL
                and isinstance(block.get("input"), dict)
            ),
            None,
        )
        if called is None:
            if data.get("stop_reason") == "max_tokens":
                raise ModelUnavailable(f"{model} ran out of output tokens before answering")
            text = "".join(
                str(block.get("text", "")) for block in blocks if block.get("type") == "text"
            )
            called = json_answer(text, model)
        usage = data.get("usage") or {}
        input_tokens = sum(
            int(usage.get(field) or 0)
            for field in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        cost = self._info.cost(input_tokens, int(usage.get("output_tokens") or 0))
        return Generated(data=called, model=str(data.get("model") or model), cost=cost)

    async def models(self) -> list[str]:
        """The models the key can use, as Anthropic lists them."""
        if self._client is None:
            raise RuntimeError("use the model inside an `async with` block")
        try:
            response = await self._client.get(f"{self._url}/models", headers=self._headers())
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"{self.name} couldn't be reached: {exc}") from exc
        if response.status_code != 200:
            raise ModelUnavailable(
                f"{self.name} answered {response.status_code}: {error_message(response)}"
            )
        listed = response.json().get("data") or []
        return [str(entry["id"]) for entry in listed if isinstance(entry, dict) and entry.get("id")]
