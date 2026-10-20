"""TypeSafe's Jev, through its REST API, as v2's Decider.

Jev answers typed questions with a probability for each answer, and it never writes text, so it
can't make an answer up. One call asks every question about the same evidence at once, which
costs barely more than one. Images are sent only when they're needed, within Jev's size limits,
and each request first takes a turn from the free tier's limits.

What Jev is weak at, from its own docs, shapes how v2 asks it: it doesn't count or do arithmetic
well, it leans toward the first option, and it reads a large state of irrelevant detail less
well. So code does the counting, options come in an order that doesn't favor the rules' pick,
and the state holds only what the question needs.
"""

import asyncio
import base64
import io
from types import TracebackType
from typing import Any, Final, Self

import httpx
from PIL import Image, UnidentifiedImageError

from bi2.core.asking import (
    Agreed,
    Answer,
    Ask,
    Choice,
    Decision,
    Found,
    Levels,
    Locate,
    Picked,
    Question,
    Rated,
    YesNo,
)
from bi2.core.errors import ModelUnavailable
from bi2.llm.limits import FreeTier
from bi2.llm.registry import model_info

_API: Final = "https://api.typesafe.ai/v1/systemone"
_BUSY: Final = frozenset({429, 500, 502, 503, 504, 529})
_TRIES: Final = 4
# Jev takes images 280 to 1568 pixels on each side.
_SMALLEST, _LARGEST = 280, 1568


def _question(question: Question) -> dict[str, Any]:
    match question:
        case Choice():
            return {
                "type": "choice",
                "instructions": question.instructions,
                "criteria": question.options,
            }
        case YesNo():
            asked: dict[str, Any] = {"type": "noul", "instructions": question.instructions}
            if question.yes or question.no:
                asked["criteria"] = {"true": question.yes or "yes", "false": question.no or "no"}
            return asked
        case Levels():
            return {
                "type": "score",
                "instructions": question.instructions,
                "criteria": list(question.levels),
            }
        case Locate():
            return {"type": "box", "instructions": question.instructions}


def fit_image(image: bytes) -> bytes:
    """The image as a PNG within Jev's limits: scaled down to at most 1568 pixels on its long
    side, and padded with white to at least 280 on each. Raises ValueError for what isn't an
    image."""
    try:
        with Image.open(io.BytesIO(image)) as opened:
            picture = opened.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("not an image") from exc
    scale = min(1.0, _LARGEST / max(picture.size))
    if scale < 1.0:
        picture = picture.resize(
            (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
        )
    width, height = max(picture.width, _SMALLEST), max(picture.height, _SMALLEST)
    if (width, height) != picture.size:
        padded = Image.new("RGB", (width, height), "white")
        padded.paste(picture, ((width - picture.width) // 2, (height - picture.height) // 2))
        picture = padded
    out = io.BytesIO()
    picture.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _answer(question: Question, answer: dict[str, Any]) -> Answer:
    match question:
        case Choice():
            return Picked(
                choice=str(answer["choice"]),
                confidence=float(answer.get("confidence", 0.0)),
                probabilities={str(k): float(v) for k, v in answer["probabilities"].items()},
            )
        case YesNo():
            return Agreed(probability=float(answer["noul"]))
        case Levels():
            return Rated(
                score=float(answer["score"]),
                confidence=float(answer.get("confidence", 0.0)),
                probabilities={int(k): float(v) for k, v in answer["probabilities"].items()},
            )
        case Locate():
            box = answer["box"]
            confidence = answer.get("confidence")
            return Found(
                top=float(box["top"]),
                left=float(box["left"]),
                bottom=float(box["bottom"]),
                right=float(box["right"]),
                confidence=None if confidence is None else float(confidence),
            )


class Jev:
    """Asks Jev. Questions about images, and Locate questions, need a model that takes images;
    Jev's own models do."""

    name = "jev"

    def __init__(
        self,
        key: str,
        *,
        limits: FreeTier,
        model: str = "jev-latest",
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = key
        self._limits = limits
        self._info = model_info(model)
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

    def _request(self, ask: Ask) -> tuple[dict[str, Any], dict[str, str]]:
        headers = {"Authorization": f"Bearer {self._key}"}
        state: str | dict[str, str] = ask.state
        body: dict[str, Any] = {
            "model": self._info.model,
            "questions": {name: _question(q) for name, q in ask.questions.items()},
        }
        needs_images = any(isinstance(q, Locate) for q in ask.questions.values())
        if ask.images or needs_images:
            headers["TypeSafe-Danger-Zone-Images"] = "true"
            # Each image is a field of the state, named as the questions refer to it, and its
            # reference is a string that appears nowhere else in the request.
            references = {
                name: f"bi2-image-{index}-{name}" for index, name in enumerate(ask.images)
            }
            state = {"evidence": ask.state} | references
            body["assets"] = {
                references[name]: {
                    "type": "image",
                    "format": "png",
                    "data_base64": base64.b64encode(fit_image(image)).decode(),
                }
                for name, image in ask.images.items()
            }
        body["state"] = state
        return body, headers

    async def decide(self, ask: Ask) -> Decision:
        """Jev's answers to every question in the Ask."""
        if self._client is None:
            raise RuntimeError("use Jev inside an `async with` block")
        try:
            body, headers = self._request(ask)
        except ValueError as exc:
            raise ModelUnavailable(f"an image for Jev couldn't be read: {exc}") from exc
        for attempt in range(_TRIES):
            last = attempt + 1 == _TRIES
            async with self._limits.turn(self._info):
                try:
                    response = await self._client.post(_API, json=body, headers=headers)
                except httpx.HTTPError as exc:
                    if last:
                        raise ModelUnavailable(f"Jev couldn't be reached: {exc}") from exc
                    await asyncio.sleep(2.0 * 2**attempt)
                    continue
            if response.status_code == 200:
                return self._decision(ask, response)
            if response.status_code not in _BUSY or last:
                raise ModelUnavailable(
                    f"Jev answered {response.status_code}: {response.text[:300]}"
                )
            await asyncio.sleep(2.0 * 2**attempt)  # Jev asks for backing off, with no delay
        raise ModelUnavailable("Jev didn't answer")  # pragma: no cover

    def _decision(self, ask: Ask, response: httpx.Response) -> Decision:
        try:
            data = response.json()
            answers = {
                name: _answer(question, data["answers"][name])
                for name, question in ask.questions.items()
            }
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ModelUnavailable(f"Jev's answer wasn't of the shape asked for: {exc}") from exc
        usage = data.get("usage", {})
        cost = self._info.cost(
            int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        )
        return Decision(answers=answers, model=str(data.get("model", self._info.model)), cost=cost)
