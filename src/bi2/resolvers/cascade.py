"""The recipe every field follows: try its steps in order, keep the first answer that's sure
enough, and record why each step was or wasn't enough. Those records are the field's audit
trail."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from bi2.core.context import RunContext
from bi2.core.errors import Bi2Error
from bi2.core.models import Evidence, FieldResult, Status, StepOutcome, StepRecord


@dataclass(frozen=True)
class Resolved[T]:
    """A step's answer, how sure it is, and what it rests on."""

    value: T
    confidence: float
    source: str  # where it came from, like "structured data + site name"
    evidence: tuple[str, ...] = ()  # quotes or URLs that support it


@dataclass(frozen=True)
class Escalate:
    """A step had no answer to give, so the next step runs."""

    reason: str


type Step[T] = Callable[[Evidence, RunContext], Awaitable[Resolved[T] | Escalate]]


def _name(step: Callable[..., Any]) -> str:
    return getattr(step, "__name__", repr(step))


async def run_cascade[T](steps: Sequence[Step[T]], ev: Evidence, ctx: RunContext) -> FieldResult[T]:
    """Run a field's steps in order, the same way for every field.

    - The first answer at least as sure as the accept threshold is the value, and the field
      is ok.
    - If no answer gets there, the surest one is kept and the field needs review, so the
      analyst has a starting point.
    - With no answer at all, the field is not found; if every step failed, it's an error.
      Nothing is ever guessed.
    """
    accept = ctx.settings.thresholds.accept
    records: list[StepRecord] = []
    best: Resolved[T] | None = None
    for step in steps:
        try:
            outcome = await step(ev, ctx)
        except Bi2Error as exc:  # a fetch or provider failure; the next step may still work
            records.append(
                StepRecord(step=_name(step), outcome=StepOutcome.FAILED, detail=str(exc))
            )
            continue
        if isinstance(outcome, Escalate):
            records.append(
                StepRecord(step=_name(step), outcome=StepOutcome.ESCALATED, detail=outcome.reason)
            )
            continue
        confidence = round(outcome.confidence, 2)
        if confidence >= accept:
            records.append(
                StepRecord(step=_name(step), outcome=StepOutcome.RESOLVED, confidence=confidence)
            )
            return FieldResult(
                value=outcome.value,
                status=Status.OK,
                confidence=confidence,
                source=outcome.source,
                evidence=outcome.evidence,
                steps=tuple(records),
            )
        records.append(
            StepRecord(
                step=_name(step),
                outcome=StepOutcome.ESCALATED,
                detail=f"not sure enough: {confidence:.2f}, below {accept:.2f}",
                confidence=confidence,
            )
        )
        if best is None or outcome.confidence > best.confidence:
            best = outcome
    if best is not None:
        return FieldResult(
            value=best.value,
            status=Status.NEEDS_REVIEW,
            confidence=round(best.confidence, 2),
            source=best.source,
            evidence=best.evidence,
            steps=tuple(records),
        )
    failed = bool(records) and all(r.outcome is StepOutcome.FAILED for r in records)
    return FieldResult(status=Status.ERROR if failed else Status.NOT_FOUND, steps=tuple(records))


def not_built_yet() -> FieldResult[Any]:
    """The result for a field v2 doesn't resolve yet: not found, with a step that says so."""
    record = StepRecord(
        step="not_built_yet", outcome=StepOutcome.ESCALATED, detail="this field isn't built yet"
    )
    return FieldResult(status=Status.NOT_FOUND, steps=(record,))
