"""Scores a set of results against the gold set, and sums up accuracy, cost and speed."""

from collections import Counter
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from bi2.core.models import Cost, SiteResult
from bi2.evaluation.gold import GoldSet, site_key
from bi2.evaluation.scoring import SCORED_FIELDS, FieldScore, Verdict, score_site


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SiteScore(_Strict):
    """How one gold-set site did."""

    url: str
    category: str
    confirmed: bool
    ran: bool  # a result existed for this site
    fields: tuple[FieldScore, ...]
    cost: Cost
    seconds: float | None = None


class FieldSummary(_Strict):
    """Totals for one field across every scored site."""

    field: str
    scored: int
    correct: int
    wrong: int
    missed: int
    unexpected: int
    needs_review: int

    @property
    def accuracy(self) -> float | None:
        """The share of scored sites answered correctly, or None if none were scored."""
        return self.correct / self.scored if self.scored else None


class Report(_Strict):
    """The whole evaluation: per-field totals, cost, speed, and every site's verdicts."""

    fields: tuple[FieldSummary, ...]
    sites: tuple[SiteScore, ...]
    sites_run: int
    cost: Cost  # total across every site that ran
    seconds_per_site: float | None
    unconfirmed_sites: int  # sites whose answers no person has checked yet
    extra_results: int  # results for sites that aren't in the gold set

    @property
    def cost_per_site(self) -> Decimal | None:
        """The average cost of the sites that ran."""
        return self.cost.usd / self.sites_run if self.sites_run else None


def load_results(path: Path) -> list[SiteResult]:
    """Read results saved as JSON Lines: one SiteResult per line."""
    results = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            results.append(SiteResult.model_validate_json(line))
        except ValidationError as exc:
            raise ValueError(f"{path.name}, line {number}: {exc}") from exc
    return results


def _summarize(field: str, scores: list[SiteScore]) -> FieldSummary:
    verdicts = [score for site in scores for score in site.fields if score.field == field]
    counts = Counter(score.verdict for score in verdicts)
    return FieldSummary(
        field=field,
        scored=len(verdicts) - counts[Verdict.NOT_SCORED],
        correct=counts[Verdict.CORRECT],
        wrong=counts[Verdict.WRONG],
        missed=counts[Verdict.MISSED],
        unexpected=counts[Verdict.UNEXPECTED],
        needs_review=sum(1 for score in verdicts if score.needs_review),
    )


def build_report(
    gold: GoldSet, results: Iterable[SiteResult], *, confirmed_only: bool = False
) -> Report:
    """Score results against the gold set. Results are matched to sites by URL."""
    by_site: dict[str, SiteResult] = {}
    for result in results:
        key = site_key(result.page.url)
        if key in by_site:
            raise ValueError(f"more than one result for {result.page.url}")
        by_site[key] = result

    sites = [site for site in gold.sites if site.confirmed or not confirmed_only]
    scores = []
    for site in sites:
        found = by_site.get(site_key(site.url))
        scores.append(
            SiteScore(
                url=site.url,
                category=site.category,
                confirmed=site.confirmed,
                ran=found is not None,
                fields=score_site(site, found),
                cost=found.cost if found else Cost(),
                seconds=found.seconds if found else None,
            )
        )

    ran = [score for score in scores if score.ran]
    gold_keys = {site_key(site.url) for site in gold.sites}
    return Report(
        fields=tuple(_summarize(field, scores) for field in SCORED_FIELDS),
        sites=tuple(scores),
        sites_run=len(ran),
        cost=sum((score.cost for score in ran), Cost()),
        seconds_per_site=sum(score.seconds or 0.0 for score in ran) / len(ran) if ran else None,
        unconfirmed_sites=sum(1 for site in sites if not site.confirmed),
        extra_results=sum(1 for key in by_site if key not in gold_keys),
    )
