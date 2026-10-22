"""Any provider that speaks OpenAI's chat completions API, as v2's LanguageModel: OpenAI itself,
Mistral, Groq, DeepSeek, xAI, OpenRouter, Together, Fireworks, Cerebras, Cohere, Perplexity,
Hugging Face, and servers on the user's own machine like Ollama, LM Studio and vLLM.

Answers are JSON of the shape each prompt asks for. A provider is first asked the way
data/providers.toml says: with the JSON schema, or for any JSON object with the schema in the
instructions, or in words alone. One that refuses is asked the next way, and the client
remembers, so a new provider works without being told what it takes. A request field a model
refuses, like a reasoning model's temperature, is dropped the same way. Each request first takes
a turn from the model's limits, and a busy or rate-limited provider is asked again after a pause.
"""

import asyncio
import base64
from types import TracebackType
from typing import Any, Final, Self

import httpx

from bi2.core.asking import Generated, Prompt
from bi2.core.errors import BudgetUsedUp, ModelUnavailable
from bi2.core.providers import JsonMode, ProviderSettings
from bi2.llm.common import (
    BUSY,
    TRIES,
    error_message,
    json_answer,
    media_type,
    retry_after,
    with_schema,
)
from bi2.llm.limits import FreeTier
from bi2.llm.registry import ModelInfo

_LOOSER: Final[dict[JsonMode, JsonMode | None]] = {
    "schema": "object",
    "object": "text",
    "text": None,
}
_ABOUT_JSON: Final = ("response_format", "json_schema", "json_object", "structured output")
# Output room for reasoning models, whose thinking counts as output: a short JSON answer still
# needs room for the thinking before it. Only the tokens used are paid for.
_LEAST_OUTPUT: Final = 2048
# Words in a refusal that say the account's quota or credit is used up, not just the minute's.
_USED_UP: Final = ("insufficient_quota", "quota", "credit", "billing", "exceeded your")


class OpenAICompatible:
    """Asks one model on an OpenAI-compatible chat completions API."""

    def __init__(
        self,
        key: str | None,
        *,
        name: str,
        provider: ProviderSettings,
        info: ModelInfo,
        limits: FreeTier,
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
        self._mode: JsonMode = provider.json_mode
        self._token_field = provider.token_param
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
        return {"Authorization": f"Bearer {self._key}"} if self._key else {}

    def _body(self, prompt: Prompt) -> dict[str, Any]:
        instructions = prompt.instructions
        if self._mode != "schema":
            instructions = with_schema(instructions, prompt.answer_schema)
        content: str | list[dict[str, Any]] = prompt.evidence
        if prompt.images:
            content = [{"type": "text", "text": prompt.evidence}]
            for image in prompt.images:
                url = f"data:{media_type(image)};base64,{base64.b64encode(image).decode()}"
                content.append({"type": "image_url", "image_url": {"url": url}})
        body: dict[str, Any] = {
            "model": self._info.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": content},
            ],
            self._token_field: max(prompt.max_output_tokens, _LEAST_OUTPUT),
        }
        if "temperature" not in self._refused:
            body["temperature"] = self._temperature
        if self._info.thinking and "reasoning_effort" not in self._refused:
            body["reasoning_effort"] = self._info.thinking
        if self._mode == "schema":
            schema = {"name": "answer", "schema": prompt.answer_schema}
            body["response_format"] = {"type": "json_schema", "json_schema": schema}
        elif self._mode == "object":
            body["response_format"] = {"type": "json_object"}
        return body

    def _ask_another_way(self, message: str, body: dict[str, Any]) -> bool:
        """Whether a refused request can be asked again another way: without a field the model
        refuses, under the other name for the output limit, or with a looser way of asking for
        JSON. Each way is tried once, so asking again always ends."""
        said = message.lower()
        for field in ("temperature", "reasoning_effort"):
            if field in body and field in said and field not in self._refused:
                self._refused.add(field)
                return True
        if "max_tokens" in said and self._token_field == "max_tokens" and "max_completion" in said:
            self._token_field = "max_completion_tokens"
            return True
        if any(word in said for word in _ABOUT_JSON) and (looser := _LOOSER[self._mode]):
            self._mode = looser
            return True
        return False

    async def generate(self, prompt: Prompt) -> Generated:
        """The model's answer. Raises ModelUnavailable when it can't answer, and BudgetUsedUp
        when that's because the account's quota or credit is used up."""
        if prompt.search:
            raise ModelUnavailable(
                f"{self.name} can't search the web here: web search needs a Gemini model,"
                " set as ai.search_model"
            )
        if self._client is None:
            raise RuntimeError("use the model inside an `async with` block")
        url = f"{self._url}/chat/completions"
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
                    raise ModelUnavailable(f"{self.name} couldn't be reached at {url}: {problem}")
                await asyncio.sleep(2.0 * 2.0**attempt)
                continue
            if response.status_code == 200:
                return self._generated(response)
            message = error_message(response)
            if response.status_code in (400, 422) and self._ask_another_way(message, body):
                continue  # asked another way, which isn't another try
            if response.status_code in (401, 403):
                raise ModelUnavailable(
                    f"{self.name} refused the key ({response.status_code}): {message}"
                )
            if response.status_code == 429 and any(word in message.lower() for word in _USED_UP):
                raise BudgetUsedUp(f"{self.name}: {message}")
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
        choices = data.get("choices") or []
        if not choices:
            raise ModelUnavailable(f"{model} gave no answer")
        choice = choices[0]
        message = choice.get("message") or {}
        if refusal := message.get("refusal"):
            raise ModelUnavailable(f"{model} refused to answer: {str(refusal)[:120]}")
        content = message.get("content")
        if isinstance(content, list):  # some servers answer in parts
            content = "".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        text = str(content or "")
        if not text.strip() and choice.get("finish_reason") == "length":
            raise ModelUnavailable(f"{model} ran out of output tokens before answering")
        answer = json_answer(text, model)
        usage = data.get("usage") or {}
        cost = self._info.cost(
            int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
        )
        return Generated(data=answer, model=str(data.get("model") or model), cost=cost)

    async def models(self) -> list[str]:
        """The models the key can use, as the provider lists them."""
        if self._client is None:
            raise RuntimeError("use the model inside an `async with` block")
        try:
            response = await self._client.get(f"{self._url}/models", headers=self._headers())
        except httpx.HTTPError as exc:
            raise ModelUnavailable(
                f"{self.name} couldn't be reached at {self._url}: {exc}"
            ) from exc
        if response.status_code != 200:
            raise ModelUnavailable(
                f"{self.name} answered {response.status_code}: {error_message(response)}"
            )
        listed = response.json().get("data") or []
        return sorted(
            str(entry["id"]) for entry in listed if isinstance(entry, dict) and entry.get("id")
        )
