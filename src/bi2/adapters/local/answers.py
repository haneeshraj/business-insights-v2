"""Model answers kept on disk, and the log of every model call.

A run on saved pages keeps each answer beside the pages, so a rerun asks no model at all and
gets the same answers, the way it gets the same downloads. A live run keeps them in the user's
cache folder. Answers are found by a hash of everything that went into the question: the task,
its prompt version, the model, the evidence and the images. A changed prompt or new evidence is
a new question.
"""

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bi2.core.asking import Ask, Decision, Generated, Prompt
from bi2.core.errors import ModelUnavailable
from bi2.core.models import Cost
from bi2.core.ports import Decider, LanguageModel


def _hash(kind: str, who: str, request: dict[str, Any], images: list[bytes]) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps([kind, who, request], sort_keys=True, default=str).encode())
    for image in images:
        digest.update(hashlib.sha256(image).digest())
    return digest.hexdigest()


async def _read(place: Path) -> str | None:
    if not await asyncio.to_thread(place.is_file):
        return None
    return await asyncio.to_thread(place.read_text, encoding="utf-8")


async def _write(place: Path, text: str) -> None:
    def write() -> None:
        place.parent.mkdir(parents=True, exist_ok=True)
        place.write_text(text, encoding="utf-8", newline="\n")

    await asyncio.to_thread(write)


class KeptDecisions:
    """A Decider that keeps every Decision in a folder and answers from it when it can."""

    def __init__(self, decider: Decider, folder: Path, *, model: str = "") -> None:
        self._decider = decider
        self._folder = folder
        self._model = model  # part of the key, so another model's answers aren't reused

    @property
    def name(self) -> str:
        """The kept Decider's name."""
        return self._decider.name

    async def decide(self, ask: Ask) -> Decision:
        """The kept answer to the same Ask, or the Decider's, which is then kept."""
        request = ask.model_dump(mode="json", exclude={"images"})
        key = _hash("decide", f"{self.name}:{self._model}", request, list(ask.images.values()))
        place = self._folder / ask.task / f"{key}.json"
        if (kept := await _read(place)) is not None:
            return Decision.model_validate_json(kept).model_copy(update={"cached": True})
        decision = await self._decider.decide(ask)
        await _write(place, decision.model_dump_json(indent=2))
        return decision


class KeptGenerations:
    """A LanguageModel that keeps every answer in a folder and answers from it when it can."""

    def __init__(self, llm: LanguageModel, folder: Path, *, model: str = "") -> None:
        self._llm = llm
        self._folder = folder
        self._model = model

    @property
    def name(self) -> str:
        """The kept model's name."""
        return self._llm.name

    async def generate(self, prompt: Prompt) -> Generated:
        """The kept answer to the same Prompt, or the model's, which is then kept."""
        request = prompt.model_dump(mode="json", exclude={"images"})
        key = _hash("generate", f"{self.name}:{self._model}", request, list(prompt.images))
        place = self._folder / prompt.task / f"{key}.json"
        if (kept := await _read(place)) is not None:
            return Generated.model_validate_json(kept).model_copy(update={"cached": True})
        generated = await self._llm.generate(prompt)
        await _write(place, generated.model_dump_json(indent=2))
        return generated


class CallLog:
    """Writes one line per model call to a JSON Lines file, and adds up what was spent."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self.spent = Cost()  # on calls that reached a model in this run
        self.calls = 0
        self.kept = 0  # calls answered from kept answers
        self.failed = 0

    async def record(
        self, *, who: str, task: str, version: str, model: str, cost: Cost, cached: bool,
        seconds: float, problem: str = "",
    ) -> None:  # fmt: skip
        """Log one call."""
        async with self._lock:
            self.calls += 1
            self.failed += bool(problem)
            self.kept += cached
            if not cached:
                self.spent += cost
            if self._path is None:
                return
            line = {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "who": who, "task": task, "version": version, "model": model,
                "input_tokens": cost.input_tokens, "output_tokens": cost.output_tokens,
                "usd": str(cost.usd), "cached": cached, "seconds": round(seconds, 2),
                "problem": problem,
            }  # fmt: skip
            text = json.dumps(line) + "\n"
            path = self._path

            def append() -> None:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8", newline="\n") as file:
                    file.write(text)

            await asyncio.to_thread(append)


class LoggedDecider:
    """A Decider whose every call goes in the call log."""

    def __init__(self, decider: Decider, log: CallLog) -> None:
        self._decider = decider
        self._log = log

    @property
    def name(self) -> str:
        """The logged Decider's name."""
        return self._decider.name

    async def decide(self, ask: Ask) -> Decision:
        """The Decider's answers, logged."""
        started = time.monotonic()
        try:
            decision = await self._decider.decide(ask)
        except ModelUnavailable as exc:
            await self._log.record(
                who=self.name, task=ask.task, version=ask.version, model="", cost=Cost(),
                cached=False, seconds=time.monotonic() - started, problem=str(exc)[:300],
            )  # fmt: skip
            raise
        await self._log.record(
            who=self.name, task=ask.task, version=ask.version, model=decision.model,
            cost=decision.cost, cached=decision.cached, seconds=time.monotonic() - started,
        )  # fmt: skip
        return decision


class LoggedModel:
    """A LanguageModel whose every call goes in the call log."""

    def __init__(self, llm: LanguageModel, log: CallLog) -> None:
        self._llm = llm
        self._log = log

    @property
    def name(self) -> str:
        """The logged model's name."""
        return self._llm.name

    async def generate(self, prompt: Prompt) -> Generated:
        """The model's answer, logged."""
        started = time.monotonic()
        try:
            generated = await self._llm.generate(prompt)
        except ModelUnavailable as exc:
            await self._log.record(
                who=self.name, task=prompt.task, version=prompt.version, model="", cost=Cost(),
                cached=False, seconds=time.monotonic() - started, problem=str(exc)[:300],
            )  # fmt: skip
            raise
        await self._log.record(
            who=self.name, task=prompt.task, version=prompt.version, model=generated.model,
            cost=generated.cost, cached=generated.cached, seconds=time.monotonic() - started,
        )  # fmt: skip
        return generated
