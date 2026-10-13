"""Tests for comparing two runs, and for scoring a changed answer against the right answers
people gave."""

from bi2.evaluation.compare import Totals, compare_runs
from bi2.evaluation.gold import GoldSite, site_key
from bi2.evaluation.learning import label_answers
from bi2.evaluation.verifications import Verification
from bi2.pipeline import failed_result
from tests.evaluation.test_learning import WHEN
from tests.factories import answered, site_result

URL = "https://example-cafe.ca/"
GOLD = {
    site_key(URL): GoldSite(
        url=URL, category="cafe", company_names=("Example Cafe",), phones=("+14165550123",)
    )
}


def _check(field: str, answer: str, verdict: str, correct: str = "") -> Verification:
    return Verification.model_validate(
        {
            "site": URL,
            "field": field,
            "answer": answer,
            "shown": answer,
            "verdict": verdict,
            "correct": correct,
            "status": "ok",
            "checked_at": WHEN,
        }
    )


def test_a_changed_answer_is_scored_against_the_right_answer_you_gave() -> None:
    wrong = _check("phone", "+14165550199", "wrong", correct="+14165550123")
    checks = {wrong.key: wrong}
    for number, right in (("+14165550123", True), ("+14165550100", False)):
        later = site_result(URL, phone=answered(number))
        [label] = [label for label in label_answers([later], {}, checks) if label.field == "phone"]
        assert (label.right, label.by) == (right, "your answers")


def test_nothing_to_find_counts_as_none() -> None:
    nothing = _check("social_links", "", "right")
    profiles = [{"platform": "instagram", "url": "https://instagram.com/someone"}]
    later = site_result(URL, social_links=answered(profiles))
    labels = {label.field: label for label in label_answers([later], {}, {nothing.key: nothing})}
    assert (labels["social_links"].right, labels["social_links"].by) == (False, "your answers")


def test_changes_are_judged_better_worse_or_the_same() -> None:
    before = [
        site_result(
            URL,
            company_name=answered("Someone Else"),
            phone=answered("+14165550123"),
            logo=answered({"url": f"{URL}logo.png"}),
        )
    ]
    after = [
        site_result(
            URL,
            company_name=answered("Example Cafe"),
            phone=answered("+14165550199"),
            logo=answered({"url": f"{URL}new-logo.png"}),
        )
    ]
    comparison = compare_runs(before, after, GOLD, {})
    verdicts = {change.field: change.verdict for change in comparison.changes}
    assert verdicts == {"company_name": "better", "phone": "worse", "logo": "not checked"}
    assert comparison.worse
    assert comparison.after["company_name"] == Totals(checked=1, right=1, right_and_sure=1)
    assert compare_runs(after, after, GOLD, {}).changes == []


def test_a_site_that_no_longer_loads_counts_as_worse() -> None:
    before = [site_result(URL, company_name=answered("Example Cafe"))]
    comparison = compare_runs(before, [failed_result(URL, "refused", 1.0)], GOLD, {})
    assert (comparison.failed_now, comparison.changes, comparison.worse) == ([URL], [], True)
