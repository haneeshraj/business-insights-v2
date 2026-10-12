"""What checked answers teach: whether each answer was right, which of four groups it's in, and
the decision of which answers to keep without AI.

An answer counts as checked when a person marked it on the review page, or when the gold set
can score it. A person's check wins, since the gold set can be wrong: it lists one file for a
logo that has several.

The four groups, by what v2 did with an answer and whether it was right:

- kept, and right: a true positive. These stay as they are, with no AI.
- kept, but wrong: a false positive. The costly mistake.
- sent on, but right: a false negative. Work the AI step didn't need to do.
- sent on, and wrong: a true negative. What the AI step is for.

The decision groups each field's checked answers by confidence, and keeps a group without AI
only when enough of its answers were right (see core/routing.py).
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from enum import StrEnum
from typing import NamedTuple

from bi2.core.models import SiteResult, Status
from bi2.core.routing import Group, Routing
from bi2.evaluation.gold import GoldSite, site_key
from bi2.evaluation.scoring import Verdict, score_site
from bi2.evaluation.verifications import CheckKey, Verification, answer_key


class Outcome(StrEnum):
    """Which of the four groups an answer is in."""

    TRUE_POSITIVE = "kept, right"
    FALSE_POSITIVE = "kept, wrong"
    FALSE_NEGATIVE = "sent on, right"
    TRUE_NEGATIVE = "sent on, wrong"


class Label(NamedTuple):
    """Whether one answer was right, who said so, and what v2 had done with it."""

    site: str
    field: str
    right: bool
    kept: bool  # v2 accepted it without sending it on
    confidence: float | None  # None when v2 found nothing
    by: str  # "you" or "gold set"
    note: str = ""

    @property
    def outcome(self) -> Outcome:
        if self.kept:
            return Outcome.TRUE_POSITIVE if self.right else Outcome.FALSE_POSITIVE
        return Outcome.FALSE_NEGATIVE if self.right else Outcome.TRUE_NEGATIVE


def _not_built(result: SiteResult, field: str) -> bool:
    steps = result.field_results[field].steps
    return bool(steps) and steps[0].step == "not_built_yet"


def label_answers(
    results: Iterable[SiteResult],
    gold: dict[str, GoldSite],
    checks: dict[CheckKey, Verification],
) -> list[Label]:
    """A label for every checked answer. Sites that failed and fields not built yet have
    none: they'd say nothing about how v2 decides."""
    labels: list[Label] = []
    for result in results:
        if result.error:
            continue
        key = site_key(result.page.url)
        entry = gold.get(key)
        scores = {score.field: score for score in score_site(entry, result)} if entry else {}
        for field, answer in result.field_results.items():
            if _not_built(result, field):
                continue
            check = checks.get((key, field, answer_key(field, answer)))
            if check is not None:
                right, by, note = check.verdict == "right", "you", check.note
            else:
                score = scores.get(field)
                if score is None or score.verdict is Verdict.NOT_SCORED:
                    continue
                right, by, note = score.verdict is Verdict.CORRECT, "gold set", ""
            kept = answer.status is Status.OK
            labels.append(Label(result.page.url, field, right, kept, answer.confidence, by, note))
    return labels


def tally(labels: Iterable[Label]) -> dict[str, Counter[Outcome]]:
    """How many answers of each field are in each of the four groups."""
    counts: dict[str, Counter[Outcome]] = defaultdict(Counter)
    for label in labels:
        counts[label.field][label.outcome] += 1
    return dict(counts)


def learn_routing(
    labels: Iterable[Label], *, target: float = 0.95, min_checked: int = 5
) -> Routing:
    """The decision these labels teach: for each field and confidence, how many checked
    answers there were and how many were right. Answers with nothing found aren't grouped."""
    groups: dict[str, dict[float, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for label in labels:
        if label.confidence is not None:
            groups[label.field][round(label.confidence, 2)].append(label.right)
    return Routing(
        target=target,
        min_checked=min_checked,
        groups={
            field: tuple(
                Group(confidence=confidence, checked=len(rights), right=sum(rights))
                for confidence, rights in sorted(by_confidence.items(), reverse=True)
            )
            for field, by_confidence in groups.items()
        },
    )
