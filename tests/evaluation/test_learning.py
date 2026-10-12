"""Tests for checks, labels, the four groups and the learned decision."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bi2.core.models import SiteResult, Status
from bi2.evaluation.gold import GoldSite, site_key
from bi2.evaluation.learning import Outcome, Record, by_confidence, label_answers, tally
from bi2.evaluation.verifications import (
    Verification,
    add_verification,
    answer_key,
    answer_text,
    load_verifications,
)
from bi2.resolvers.cascade import not_built_yet
from tests.factories import answered, site_result

URL = "https://example-cafe.ca/"
WHEN = datetime(2026, 10, 12, tzinfo=UTC)
GOLD = {
    site_key(URL): GoldSite(
        url=URL,
        category="cafe",
        company_names=("Example Cafe",),
        phones=("+14165550123",),
        logo_urls=(f"{URL}logo.png",),
    )
}


def _result(**fields: Any) -> SiteResult:
    return site_result(URL, mcc=not_built_yet().model_dump(), **fields)


def _check(field: str, answer: str, verdict: str, note: str = "") -> Verification:
    return Verification.model_validate(
        {
            "site": URL,
            "field": field,
            "answer": answer,
            "verdict": verdict,
            "note": note,
            "status": "ok",
            "confidence": 0.9,
            "checked_at": WHEN,
        }
    )


def test_answers_match_however_they_are_written() -> None:
    result = _result(company_name=answered("EXAMPLE CAFE LTD."))
    assert answer_key("company_name", result.company_name) == "example cafe"
    assert answer_text("company_name", result.company_name) == "EXAMPLE CAFE LTD."
    assert answer_key("phone", result.phone) == ""  # nothing found


def test_checks_are_saved_and_the_newest_wins(tmp_path: Path) -> None:
    path = tmp_path / "verifications.jsonl"
    add_verification(path, _check("phone", "+14165550123", "wrong"))
    add_verification(path, _check("phone", "+14165550123", "right", "it's on their contact page"))
    checks = load_verifications(path)
    assert len(checks) == 1
    assert next(iter(checks.values())).note == "it's on their contact page"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2  # history is kept


def test_labels_come_from_the_gold_set_and_your_checks_win() -> None:
    result = _result(
        company_name=answered("Example Cafe"),
        phone=answered("+14165550199", confidence=0.6, status="needs_review"),
        logo=answered({"url": f"{URL}images/logo-dark.png"}),
    )
    yours = _check("logo", answer_key("logo", result.logo), "right", "the dark copy of the logo")
    labels = {label.field: label for label in label_answers([result], GOLD, {yours.key: yours})}
    assert labels["company_name"].outcome is Outcome.TRUE_POSITIVE
    assert labels["phone"].outcome is Outcome.TRUE_NEGATIVE  # sent on, and wrong
    assert (labels["logo"].by, labels["logo"].outcome) == ("you", Outcome.TRUE_POSITIVE)
    assert labels["logo"].note == "the dark copy of the logo"
    assert "mcc" not in labels  # not built yet, so it says nothing


def test_the_four_groups_and_the_record_by_confidence_are_counted() -> None:
    results = [
        site_result(f"https://cafe-{n}.ca/", company_name=answered(f"Cafe {n}", confidence=0.9))
        for n in range(6)
    ]
    gold = {
        site_key(r.page.url): GoldSite(
            url=r.page.url,
            category="cafe",
            company_names=(f"Cafe {n}" if n < 4 else "Someone Else",),
        )
        for n, r in enumerate(results)
    }
    labels = label_answers(results, gold, {})
    assert tally(labels)["company_name"] == {Outcome.TRUE_POSITIVE: 4, Outcome.FALSE_POSITIVE: 2}
    assert by_confidence(labels) == {"company_name": (Record(0.9, checked=6, right=4),)}
    assert results[0].company_name.status is Status.OK
