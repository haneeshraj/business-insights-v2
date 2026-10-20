"""What v2 asks models, and what they answer.

There are two kinds of model calls:

- **A decision** asks typed questions about some evidence: pick one of these options, yes or
  no, rate against these levels, or find something in an image. Jev answers them natively, with
  a probability for each answer. An LLM can stand in for it, less well calibrated.
- **A generation** asks an LLM for a JSON answer of a given shape, for what a decision can't
  do, like quoting an address out of a page's text.

Both name their task and its prompt version, which go into the call log and the cache key, so
a changed prompt is never answered from an old cache.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from bi2.core.models import Confidence, Cost


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Decisions ----------------------------------------------------------------


class Choice(_Frozen):
    """Pick one of the options. Each option has a short key and a description of what it means."""

    kind: Literal["choice"] = "choice"
    instructions: str = Field(min_length=1)
    options: dict[str, str] = Field(min_length=1, max_length=255)


class YesNo(_Frozen):
    """A yes-or-no question, with what counts as yes and as no when it needs saying."""

    kind: Literal["yes_no"] = "yes_no"
    instructions: str = Field(min_length=1)
    yes: str = ""
    no: str = ""


class Levels(_Frozen):
    """Rate against ordered levels, lowest first."""

    kind: Literal["levels"] = "levels"
    instructions: str = ""
    levels: tuple[str, ...] = Field(min_length=1, max_length=10)


class Locate(_Frozen):
    """Find something in one of the images and give its box."""

    kind: Literal["locate"] = "locate"
    instructions: str = Field(min_length=1)


Question = Annotated[Choice | YesNo | Levels | Locate, Field(discriminator="kind")]


class Ask(_Frozen):
    """Questions about one piece of evidence, asked together in one call.

    `state` is the evidence as text. Images go in `images` by name, and the state and the
    questions refer to them by that name in backticks, like `screenshot`."""

    task: str = Field(min_length=1)  # like "logo_pick"; names the call in logs and the cache
    version: str = Field(min_length=1)  # the prompt's version; changing it skips the cache
    state: str
    questions: dict[str, Question] = Field(min_length=1)
    images: dict[str, bytes] = Field(default_factory=dict)  # PNG or JPEG, by name


class Picked(_Frozen):
    """The option picked, how sure the model is, and the probability of every option."""

    kind: Literal["choice"] = "choice"
    choice: str
    confidence: Confidence
    probabilities: dict[str, float] = Field(default_factory=dict)

    def probability(self, option: str) -> float:
        """The probability of one option."""
        return self.probabilities.get(option, 0.0)


class Agreed(_Frozen):
    """The probability that the answer to a yes-or-no question is yes."""

    kind: Literal["yes_no"] = "yes_no"
    probability: Confidence


class Rated(_Frozen):
    """The level, as a probability-weighted average that can fall between levels."""

    kind: Literal["levels"] = "levels"
    score: float = Field(ge=0)
    confidence: Confidence
    probabilities: dict[int, float] = Field(default_factory=dict)


class Found(_Frozen):
    """Where something is in an image, as fractions of its width and height from the top
    left."""

    kind: Literal["locate"] = "locate"
    top: Confidence
    left: Confidence
    bottom: Confidence
    right: Confidence
    confidence: Confidence | None = None


Answer = Annotated[Picked | Agreed | Rated | Found, Field(discriminator="kind")]


class Decision(_Frozen):
    """A model's answers to an Ask, by question name."""

    answers: dict[str, Answer]
    model: str  # the model that answered, like "jev-1.13.0"
    cost: Cost = Field(default_factory=Cost)
    cached: bool = False  # answered from an earlier run's copy, with nothing spent now

    def picked(self, question: str) -> Picked:
        """The answer to a choice question."""
        answer = self.answers[question]
        if not isinstance(answer, Picked):
            raise TypeError(f"{question} wasn't a choice question")
        return answer

    def agreed(self, question: str) -> Agreed:
        """The answer to a yes-or-no question."""
        answer = self.answers[question]
        if not isinstance(answer, Agreed):
            raise TypeError(f"{question} wasn't a yes-or-no question")
        return answer

    def found(self, question: str) -> Found:
        """The answer to a locate question."""
        answer = self.answers[question]
        if not isinstance(answer, Found):
            raise TypeError(f"{question} wasn't a locate question")
        return answer


# --- Generations --------------------------------------------------------------


class Prompt(_Frozen):
    """A request for a JSON answer of a given shape.

    The fixed instructions come first and the evidence last, so the providers' prompt caching
    covers the part that repeats. Page text in the evidence is data, never instructions."""

    task: str = Field(min_length=1)
    version: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    evidence: str
    images: tuple[bytes, ...] = ()  # PNG or JPEG, shown after the evidence
    answer_schema: dict[str, Any]  # a JSON schema the answer must match
    max_output_tokens: int = Field(default=1024, ge=16, le=16384)


class Generated(_Frozen):
    """An LLM's JSON answer to a Prompt."""

    data: dict[str, Any]
    model: str
    cost: Cost = Field(default_factory=Cost)
    cached: bool = False
