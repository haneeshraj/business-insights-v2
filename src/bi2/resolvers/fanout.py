"""One Jev call for a site's questions, instead of one per field: Jev's fan-out pattern.

The seven resolvers run at once, and several may need Jev in the same moment: the MCC's first
round, the logo's numbered boxes, the main phone number. Jev answers many questions about one
state in one call for barely more than one costs, and on its free tier calls are what's
counted, so the site's questions wait for each other and go together.

The questions go when every resolver still running is waiting for Jev. That makes each call's
questions the same on every run, whatever the timing, so kept answers still match on reruns.
Each Ask's evidence stays in its own labeled section of the state, and each question is told
to answer from its own section only. A lone question goes as it is, and so does one with a
long list of options, like the MCC's first round.
"""

import asyncio
import re
from dataclasses import dataclass, field

from bi2.core.asking import Ask, Decision, Question
from bi2.core.models import Cost
from bi2.core.ports import Decider


@dataclass
class _Waiting:
    ask: Ask
    answer: asyncio.Future[Decision]


@dataclass
class FanOut:
    """A Decider for one site's resolvers, which sends their questions together."""

    decider: Decider
    running: int  # resolvers that haven't finished yet
    _waiting: list[_Waiting] = field(default_factory=list)
    # The calls in flight, kept so none is collected before it's done: the event loop holds
    # only weak references to its tasks.
    _sending: set[asyncio.Task[None]] = field(default_factory=set)

    @property
    def name(self) -> str:
        """The Decider's name."""
        return self.decider.name

    async def decide(self, ask: Ask) -> Decision:
        """The answers to one resolver's Ask, sent with the others' when they're ready."""
        answer: asyncio.Future[Decision] = asyncio.get_running_loop().create_future()
        self._waiting.append(_Waiting(ask, answer))
        self._send_when_ready()
        return await answer

    def finished(self) -> None:
        """Record that a resolver is done, which may let the others' questions go."""
        self.running -= 1
        self._send_when_ready()

    def _send_when_ready(self) -> None:
        if self._waiting and len(self._waiting) >= self.running:
            batch, self._waiting = self._waiting, []
            loop = asyncio.get_running_loop()
            # A question with a long list, like the MCC's first round, goes on its own: small
            # questions read less well beside it.
            alone = [w for w in batch if _long(w.ask)]
            together = [w for w in batch if not _long(w.ask)]
            for group in [[waiting] for waiting in alone] + ([together] if together else []):
                task = loop.create_task(self._send(group))
                self._sending.add(task)
                task.add_done_callback(self._sending.discard)

    async def _send(self, batch: list[_Waiting]) -> None:
        if len(batch) == 1:
            try:
                batch[0].answer.set_result(await self.decider.decide(batch[0].ask))
            except Exception as exc:  # noqa: BLE001  # handed to the resolver that asked
                batch[0].answer.set_exception(exc)
            return
        try:
            decision = await self.decider.decide(combine([w.ask for w in batch]))
        except Exception as exc:  # noqa: BLE001  # handed to every resolver that asked
            for waiting in batch:
                waiting.answer.set_exception(exc)
            return
        for index, waiting in enumerate(batch):
            waiting.answer.set_result(split(decision, index, waiting.ask, len(batch)))


_LONG_LIST = 60  # options in a question that make it go on its own


def _long(ask: Ask) -> bool:
    return any(len(getattr(q, "options", {})) > _LONG_LIST for q in ask.questions.values())


def _key(index: int, ask: Ask) -> str:
    return f"{index}_{ask.task}"


def _renamed(text: str, images: dict[str, str]) -> str:
    for name, new in images.items():
        text = re.sub(rf"`{re.escape(name)}`", f"`{new}`", text)
    return text


def combine(asks: list[Ask]) -> Ask:
    """Several Asks as one: each one's evidence in its own labeled section, and each question
    told to answer from its own section only."""
    states, questions, images = [], {}, {}
    for index, ask in enumerate(asks):
        key = _key(index, ask)
        renames = {name: f"{key}_{name}" for name in ask.images}
        states.append(f"[{key}]\n{_renamed(ask.state, renames)}")
        for name, data in ask.images.items():
            images[renames[name]] = data
        for name, question in ask.questions.items():
            told = (
                f"Answer from the [{key}] section only. {_renamed(question.instructions, renames)}"
            )
            questions[f"{key}__{name}"] = question.model_copy(update={"instructions": told.strip()})
    typed: dict[str, Question] = questions
    return Ask(
        task="fanout",
        version="+".join(f"{ask.task}:{ask.version}" for ask in asks) + "+fanout-1",
        state="\n\n".join(states),
        questions=typed,
        images=images,
    )


def split(decision: Decision, index: int, ask: Ask, shares: int) -> Decision:
    """One Ask's answers out of a combined Decision, with its share of the cost."""
    key = _key(index, ask)
    answers = {name: decision.answers[f"{key}__{name}"] for name in ask.questions}
    cost = decision.cost
    share = Cost(
        usd=cost.usd / shares,
        input_tokens=cost.input_tokens // shares,
        output_tokens=cost.output_tokens // shares,
        model_calls=1 if index == 0 else 0,  # the one call is counted once
    )
    return Decision(answers=answers, model=decision.model, cost=share, cached=decision.cached)
