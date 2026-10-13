"""What checked answers teach: whether each answer was right, which of four groups it's in, and
how often each field's answers were right at each confidence.

An answer counts as checked in one of five ways, and the first that applies wins:

1. A person marked that very answer right or wrong on the review page.
2. A drafted check marked it: one made from the site's own pages that no person has confirmed
   yet (eval/drafted-checks.jsonl).
3. A person confirmed or gave the right answer for that field, on this run or an earlier one,
   so a changed answer can be scored against it.
4. A drafted check did.
5. The gold set can score it.

People come before drafts, and both before the gold set, since the gold set can be wrong: it
lists one file for a logo that has several.

The four groups, by what v2 did with an answer and whether it was right:

- kept, and right: a true positive. These stay as they are, with no AI.
- kept, but wrong: a false positive. The costly mistake.
- sent on, but right: a false negative. Work the AI step didn't need to do.
- sent on, and wrong: a true negative. What the AI step is for.

The record by confidence is what a decision of which answers to send to AI will be learned
from. That decision isn't designed yet: for now an answer is kept when it's at least as sure as
the accept threshold.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from enum import StrEnum
from typing import NamedTuple

from bi2.core.models import SiteResult, Status
from bi2.evaluation.gold import GoldSite, site_key
from bi2.evaluation.scoring import FieldScore, Verdict, score_site
from bi2.evaluation.verifications import (
    CheckKey,
    Verification,
    answer_key,
    answers_from_checks,
)


class Outcome(StrEnum):
    """Which of the four groups an answer is in."""

    TRUE_POSITIVE = "kept, right"
    FALSE_POSITIVE = "kept, wrong"
    FALSE_NEGATIVE = "sent on, right"
    TRUE_NEGATIVE = "sent on, wrong"

    @property
    def term(self) -> str:
        """The group's usual name, like "false positive"."""
        return self.name.lower().replace("_", " ")


class Label(NamedTuple):
    """Whether one answer was right, who said so, and what v2 had done with it."""

    site: str
    field: str
    right: bool
    kept: bool  # v2 accepted it without sending it on
    confidence: float | None  # None when v2 found nothing
    by: str  # "you", "draft", "your answers", "drafted answers" or "gold set"; see above
    note: str = ""
    correct: str = ""  # the right answer, when a person gave one with this answer marked wrong

    @property
    def outcome(self) -> Outcome:
        if self.kept:
            return Outcome.TRUE_POSITIVE if self.right else Outcome.FALSE_POSITIVE
        return Outcome.FALSE_NEGATIVE if self.right else Outcome.TRUE_NEGATIVE


class Record(NamedTuple):
    """How many of one field's answers at one confidence were checked, and how many were right."""

    confidence: float
    checked: int
    right: int


def checkable(result: SiteResult, field: str) -> bool:
    """Whether an answer can be checked: its site was analyzed and its field is built."""
    if result.error or field not in result.field_results:
        return False
    steps = result.field_results[field].steps
    return not (steps and steps[0].step == "not_built_yet")


def _scored(entry: GoldSite | None, result: SiteResult) -> dict[str, FieldScore]:
    """The fields an answer key can score for a site."""
    if entry is None:
        return {}
    scores = score_site(entry, result)
    return {score.field: score for score in scores if score.verdict is not Verdict.NOT_SCORED}


def label_answers(
    results: Iterable[SiteResult],
    gold: dict[str, GoldSite],
    checks: dict[CheckKey, Verification],
    drafts: dict[CheckKey, Verification] | None = None,
) -> list[Label]:
    """A label for every checked answer. Sites that failed and fields not built yet have
    none: they'd say nothing about how v2 decides."""
    drafts = drafts or {}
    yours, drafted = answers_from_checks(checks.values()), answers_from_checks(drafts.values())
    labels: list[Label] = []
    for result in results:
        if result.error:
            continue
        key = site_key(result.page.url)
        answer_keys = (
            (_scored(yours.get(key), result), "your answers"),
            (_scored(drafted.get(key), result), "drafted answers"),
            (_scored(gold.get(key), result), "gold set"),
        )
        for field, answer in result.field_results.items():
            if not checkable(result, field):
                continue
            this = (key, field, answer_key(field, answer))
            check, by = checks.get(this), "you"
            if check is None:
                check, by = drafts.get(this), "draft"
            note = correct = ""
            if check is not None:
                right, note, correct = check.verdict == "right", check.note, check.correct
            else:
                scored = next(((s[field], by) for s, by in answer_keys if field in s), None)
                if scored is None:
                    continue
                right, by = scored[0].verdict is Verdict.CORRECT, scored[1]
            kept = answer.status is Status.OK
            labels.append(
                Label(result.page.url, field, right, kept, answer.confidence, by, note, correct)
            )
    return labels


def tally(labels: Iterable[Label]) -> dict[str, Counter[Outcome]]:
    """How many answers of each field are in each of the four groups."""
    counts: dict[str, Counter[Outcome]] = defaultdict(Counter)
    for label in labels:
        counts[label.field][label.outcome] += 1
    return dict(counts)


def by_confidence(labels: Iterable[Label]) -> dict[str, tuple[Record, ...]]:
    """For each field, how often its answers were right at each confidence, surest first.
    Answers with nothing found have no confidence, so they aren't counted here."""
    rights: dict[str, dict[float, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for label in labels:
        if label.confidence is not None:
            rights[label.field][round(label.confidence, 2)].append(label.right)
    return {
        field: tuple(
            Record(confidence, len(marks), sum(marks))
            for confidence, marks in sorted(by_level.items(), reverse=True)
        )
        for field, by_level in rights.items()
    }
