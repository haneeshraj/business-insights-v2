"""What the review page works from: one run's results, the gold set and your checks. It labels
every answer that can be checked, and saves each check you make, with its note and, for an
answer that's wrong, the right one, to the checks file (eval/verifications.jsonl by default).

Nothing here changes how v2 decides. The checks are for learning how often it's right: which
answers it keeps that are wrong, and which it sends on that were right.
"""

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bi2.cli.report import ReportSite, ReviewPage, label_html, learned_section, render_report
from bi2.core.models import Evidence, SiteResult
from bi2.core.urls import site_folder
from bi2.evaluation.gold import GoldSite, site_key
from bi2.evaluation.learning import Label, checkable, label_answers
from bi2.evaluation.report import load_results
from bi2.evaluation.scoring import score_site
from bi2.evaluation.verifications import (
    Verification,
    add_verification,
    answer_key,
    answer_text,
    load_verifications,
)
from bi2.evidence.contacts import normalize_phone


class NoSuchAnswer(LookupError):
    """The page asked to check an answer the run doesn't have, or one that can't be checked."""


class BadAnswer(ValueError):
    """The right answer given can't be used, like a phone number that isn't one."""


class CheckRequest(BaseModel):
    """One check, as the review page sends it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    site: str
    field: str
    verdict: Literal["right", "wrong"]
    note: str = Field(default="", max_length=1000)
    correct: str = Field(default="", max_length=2000)  # the right answer, with "wrong"


def _web_address(text: str) -> bool:
    return text.startswith(("http://", "https://")) and " " not in text


def _correct(field: str, given: str, ev: Evidence | None) -> str:
    """The right answer as a person typed it, written the way checks keep it. A logo can be
    given as its candidate number, like "#2", and is kept as that candidate's address."""
    given = given.strip()
    if not given:
        return ""
    if field == "phone":
        region = ev.countries[0] if ev is not None and ev.countries else "CA"
        number = normalize_phone(given, region)
        if number is None:
            raise BadAnswer(f"{given} isn't a phone number")
        return number
    if field == "social_links":
        profiles = given.replace(",", " ").split()
        if not all(_web_address(profile) for profile in profiles):
            raise BadAnswer("give the profiles' full addresses, starting with https://")
        return " ".join(profiles)
    if field == "logo":
        if given.startswith("#") and given[1:].isdigit():
            candidates = {c.number: c for c in ev.logo_candidates} if ev is not None else {}
            candidate = candidates.get(int(given[1:]))
            if candidate is None:
                raise BadAnswer(f"there's no logo candidate {given} on this page")
            return candidate.url or given  # an inline SVG has no address of its own
        if not _web_address(given):
            raise BadAnswer("give the logo's address, or its candidate number, like #2")
    return given


def _evidence(results_dir: Path, result: SiteResult) -> Evidence | None:
    """The evidence saved with a result. A failed site has none, even if an older run saved
    some."""
    path = results_dir / site_folder(result.page.url) / "evidence.json"
    if result.error or not path.is_file():
        return None
    return Evidence.model_validate_json(path.read_text(encoding="utf-8"))


class ReviewSession:
    """The review page's state. The server calls it from several threads, so every method
    takes the lock."""

    def __init__(self, results_dir: Path, gold: dict[str, GoldSite], checks_file: Path) -> None:
        self.results_dir = results_dir
        self.checks_file = checks_file
        self._gold = gold
        self._results = load_results(results_dir / "results.jsonl")
        self._by_url = {result.page.url: result for result in self._results}
        self._evidence = {r.page.url: _evidence(results_dir, r) for r in self._results}
        self._answers = [
            (result, field)
            for result in self._results
            for field in result.field_results
            if checkable(result, field)
        ]
        self._checks = load_verifications(checks_file)
        self._lock = threading.Lock()
        self._labels = self._label()

    def _label(self) -> dict[tuple[str, str], Label]:
        labels = label_answers(self._results, self._gold, self._checks)
        return {(label.site, label.field): label for label in labels}

    @property
    def sites(self) -> int:
        return len(self._results)

    def counts(self) -> tuple[int, int, int]:
        """How many answers can be checked, how many are, and how many of those you checked."""
        with self._lock:
            yours = sum(label.by == "you" for label in self._labels.values())
            return len(self._answers), len(self._labels), yours

    def check(self, request: CheckRequest) -> None:
        """Save a check, newest last, and label the answers again."""
        with self._lock:
            result = self._by_url.get(request.site)
            if result is None or not checkable(result, request.field):
                raise NoSuchAnswer(f"there's no {request.field} answer to check for {request.site}")
            answer = result.field_results[request.field]
            correct = ""
            if request.verdict == "wrong":
                correct = _correct(request.field, request.correct, self._evidence[request.site])
            check = Verification(
                site=request.site,
                field=request.field,
                answer=answer_key(request.field, answer),
                shown=answer_text(request.field, answer),
                verdict=request.verdict,
                note=request.note.strip(),
                correct=correct,
                status=answer.status,
                confidence=answer.confidence,
                checked_at=datetime.now(UTC),
            )
            add_verification(self.checks_file, check)
            self._checks[check.key] = check
            self._labels = self._label()

    def update(self) -> dict[str, object]:
        """What the page shows after a check: every answer's label, and the summary."""
        with self._lock:
            answers = []
            for result, field in self._answers:
                label = self._labels.get((result.page.url, field))
                yours = label is not None and label.by == "you"
                found = result.field_results[field].value is not None
                answers.append(
                    {
                        "site": result.page.url,
                        "field": field,
                        "by": label.by if label is not None else "",
                        "verdict": ("right" if label.right else "wrong") if label and yours else "",
                        "correct": label.correct if label and yours else "",
                        "label": label_html(label, found=found),
                    }
                )
            return {"answers": answers, "summary": self._learned()}

    def _learned(self) -> str:
        return learned_section(list(self._labels.values()), len(self._answers))

    def page(self, token: str, nonce: str) -> str:
        """The review page, as it stands now."""
        with self._lock:
            sites = [self._report_site(result) for result in self._results]
            return render_report(
                self.results_dir / "review.html",  # files are served relative to the folder
                sites,
                source=str(self.results_dir),
                title="Review",
                root=self.results_dir,
                review=ReviewPage(token, nonce, self._learned()),
            )

    def _report_site(self, result: SiteResult) -> ReportSite:
        url = result.page.url
        ev = self._evidence[url]
        entry = self._gold.get(site_key(url))
        return ReportSite(
            ev,
            screenshot=self.results_dir / ev.screenshot_file if ev and ev.screenshot_file else None,
            gold=entry,
            result=result,
            scores=score_site(entry, result) if entry is not None else (),
            labels={
                field: self._labels.get((url, field))
                for field in result.field_results
                if checkable(result, field)
            },
        )
