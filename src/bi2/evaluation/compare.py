"""Comparing two runs of the same sites: which answers changed, and whether each change made
things better or worse.

Answers are judged the way the review page judges them: by a person's check, then the right
answers people gave, then the gold set. From best to worst, an answer is kept and right, sent
on but right, sent on and wrong, or kept but wrong. A changed answer that's as good as before
is "the same", and one that no one has checked on both sides is "not checked": the comparison
can't tell whether it's better.
"""

from collections import defaultdict
from collections.abc import Iterable
from typing import Final, Literal, NamedTuple

from bi2.core.models import SiteResult
from bi2.evaluation.gold import GoldSite, site_key
from bi2.evaluation.learning import Label, Outcome, checkable, label_answers
from bi2.evaluation.verifications import CheckKey, Verification, answer_text

_RANK: Final = {
    Outcome.TRUE_POSITIVE: 3,
    Outcome.FALSE_NEGATIVE: 2,
    Outcome.TRUE_NEGATIVE: 1,
    Outcome.FALSE_POSITIVE: 0,
}


type Verdict = Literal["better", "worse", "the same", "not checked"]


class Change(NamedTuple):
    """One answer that differs between the runs."""

    site: str
    field: str
    before: str  # the answer and how v2 marked it, like "Example Cafe (ok)"
    after: str
    verdict: Verdict


class Totals(NamedTuple):
    """A field's checked answers in one run: how many, how many were right, and how many were
    right and kept, so no later step needs to see them."""

    checked: int
    right: int
    right_and_sure: int


class Comparison(NamedTuple):
    before: dict[str, Totals]  # by field
    after: dict[str, Totals]
    changes: list[Change]
    failed_now: list[str]  # sites that loaded before but failed this time
    loaded_now: list[str]  # sites that failed before but loaded this time

    @property
    def worse(self) -> bool:
        """Whether anything got worse, including a site that no longer loads."""
        return bool(self.failed_now) or any(change.verdict == "worse" for change in self.changes)


def _totals(labels: Iterable[Label]) -> dict[str, Totals]:
    by_field: dict[str, list[Label]] = defaultdict(list)
    for label in labels:
        by_field[label.field].append(label)
    return {
        field: Totals(
            len(labels),
            sum(label.right for label in labels),
            sum(label.right and label.kept for label in labels),
        )
        for field, labels in by_field.items()
    }


def _shown(result: SiteResult, field: str) -> str:
    answer = result.field_results[field]
    return f"{answer_text(field, answer) or 'nothing'} ({answer.status.value.replace('_', ' ')})"


def compare_runs(
    before: list[SiteResult],
    after: list[SiteResult],
    gold: dict[str, GoldSite],
    checks: dict[CheckKey, Verification],
    drafts: dict[CheckKey, Verification] | None = None,
) -> Comparison:
    """What changed between two runs of the same sites. Sites in only one run are left out."""
    labels_before, labels_after = (
        label_answers(before, gold, checks, drafts),
        label_answers(after, gold, checks, drafts),
    )
    was = {(site_key(label.site), label.field): label.outcome for label in labels_before}
    now = {(site_key(label.site), label.field): label.outcome for label in labels_after}
    earlier = {site_key(result.page.url): result for result in before}
    changes: list[Change] = []
    failed_now: list[str] = []
    loaded_now: list[str] = []
    for result in after:
        key = site_key(result.page.url)
        old = earlier.get(key)
        if old is None:
            continue
        if bool(old.error) != bool(result.error):
            (failed_now if result.error else loaded_now).append(result.page.url)
            continue
        for field in result.field_results:
            if not checkable(result, field):
                continue
            then, today = was.get((key, field)), now.get((key, field))
            shown_then, shown_today = _shown(old, field), _shown(result, field)
            if shown_then == shown_today and then == today:
                continue
            verdict: Verdict = "not checked"
            if then is not None and today is not None:
                verdict = "the same"
                if then != today:
                    verdict = "better" if _RANK[today] > _RANK[then] else "worse"
            changes.append(Change(result.page.url, field, shown_then, shown_today, verdict))
    return Comparison(
        _totals(labels_before), _totals(labels_after), changes, failed_now, loaded_now
    )
