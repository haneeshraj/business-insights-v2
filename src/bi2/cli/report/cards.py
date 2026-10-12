"""One site's card in the report: its answers, its evidence, its logo candidates as pictures,
its gold-set checks and, on the review page, your checks."""

from pathlib import Path
from typing import Final, NamedTuple

from bi2.cli.report.answers import answers_table
from bi2.cli.report.html import e, file_url, lines, link, rows, tick
from bi2.core.models import Box, Evidence, LogoCandidate, SiteResult
from bi2.core.text import names_match
from bi2.core.urls import image_key, social_key
from bi2.evaluation.coverage import FieldCoverage
from bi2.evaluation.gold import ExpectedAddress, GoldSite
from bi2.evaluation.learning import Label
from bi2.evaluation.scoring import FieldScore, Verdict
from bi2.evidence.names import name_candidates

# The screenshot is the first screen at this size; boxes inside it can be cut out of it.
_SCREEN_WIDTH, _SCREEN_HEIGHT = 1280, 800
_PREVIEW_WIDTH, _PREVIEW_HEIGHT = 156, 72
_DOT: Final = " \N{MIDDLE DOT} "
_MISSES: Final = (Verdict.WRONG, Verdict.MISSED, Verdict.UNEXPECTED)


class ReportSite(NamedTuple):
    """One site in the report. A site that couldn't be analyzed has a result but no evidence."""

    evidence: Evidence | None
    status_code: int | None = None
    loaded_with: str = ""
    screenshot: Path | None = None
    gold: GoldSite | None = None
    checks: tuple[FieldCoverage, ...] = ()  # what the evidence holds of the gold answers
    result: SiteResult | None = None
    scores: tuple[FieldScore, ...] = ()  # how the result compares with the gold answers
    labels: dict[str, Label | None] | None = None  # on the review page, by field (see answers.py)

    @property
    def url(self) -> str:
        if self.evidence is not None:
            return self.evidence.page.url
        return self.result.page.url if self.result is not None else ""


def _crop(box: Box, screenshot: str) -> str | None:
    """The part of the screenshot an element was drawn in, scaled to fit the preview."""
    fits = box.width > 0 and box.height > 0 and box.x >= 0 and box.y >= 0
    if not fits or box.x + box.width > _SCREEN_WIDTH or box.y + box.height > _SCREEN_HEIGHT:
        return None
    scale = min(1.0, _PREVIEW_WIDTH / box.width, _PREVIEW_HEIGHT / box.height)
    style = (
        f"width:{box.width * scale:.0f}px;height:{box.height * scale:.0f}px;"
        f"background:url('{screenshot}') {-box.x * scale:.1f}px {-box.y * scale:.1f}px/"
        f"{_SCREEN_WIDTH * scale:.1f}px auto no-repeat"
    )
    return f'<div class="crop" style="{e(style)}"></div>'


def _logo(candidate: LogoCandidate, screenshot: str | None, accepted: set[str]) -> str:
    """One logo candidate: what it looked like on the page, and why it ranked where it did."""
    preview = _crop(candidate.box, screenshot) if candidate.box and screenshot else None
    if preview is None and candidate.url:
        preview = (
            f'<img src="{e(candidate.url)}" alt="" loading="lazy" referrerpolicy="no-referrer">'
        )
    matches = candidate.url is not None and image_key(candidate.url) in accepted
    notes: list[str] = [candidate.kind, f"{candidate.points} points"]
    notes += ["header"] if candidate.in_header else []
    notes += ["links home"] if candidate.links_home else []
    notes += ["declared"] if candidate.declared else []
    label = candidate.alt or (candidate.url or "").rsplit("/", 1)[-1] or "inline image"
    gold = " <span class=ok>&check; gold</span>" if matches else ""
    return (
        f'<figure class="logo{" match" if matches else ""}">'
        f'<div class="preview">{preview or "<span class=muted>no preview</span>"}</div>'
        f"<figcaption><b>#{candidate.number}</b> {e(_DOT.join(notes))}{gold}"
        f'<br><span class="muted">{e(label[:60])}</span></figcaption></figure>'
    )


def _expected(check: str, gold: GoldSite) -> str:
    """What the gold set expects, for showing next to a check."""
    if check == "page_kind":
        return gold.page_kind.value + (f" ({gold.platform})" if gold.platform else "")
    if check == "company_name":
        return " | ".join(gold.company_names or ())
    if check.startswith("logo") and isinstance(gold.logo_urls, tuple):
        return lines(link(url, url.rsplit("/", 1)[-1]) for url in gold.logo_urls)
    if check.startswith("address") and isinstance(gold.address, ExpectedAddress):
        parts = (gold.address.street, gold.address.city, gold.address.postal_code)
        return ", ".join(part for part in parts if part)
    if check.startswith("country") and isinstance(gold.address, ExpectedAddress):
        return gold.address.country or ""
    if check == "phone" and isinstance(gold.phones, tuple):
        return ", ".join(gold.phones)
    if check == "social_links" and isinstance(gold.social_links, tuple):
        return lines(link(url) for url in gold.social_links)
    return ""


def _checks(site: ReportSite) -> str:
    if site.gold is None or not site.checks:
        return ""
    body = "".join(
        f'<tr><td class="{"ok" if c.found else "miss"}">{"&check;" if c.found else "&cross;"}</td>'
        f"<td>{e(c.check)}</td><td>{e(c.where)}</td><td>{_expected(c.check, site.gold)}</td></tr>"
        for c in site.checks
    )
    head = "<tr><th></th><th>Gold check</th><th>Found in</th><th>Gold answer</th></tr>"
    return f'<table class="checks">{head}{body}</table>'


def _facts(ev: Evidence, gold: GoldSite | None) -> str:
    """The evidence for one site, with a tick on each value the gold set accepts."""
    gold_names = (gold.company_names or ()) if gold else ()
    gold_social = gold.social_links if gold and isinstance(gold.social_links, tuple) else ()
    first_place: dict[str, str] = {}  # each name once, with the first place it was found
    for where, name in name_candidates(ev):
        first_place.setdefault(name, where)
    names = [
        f"{e(name)} <span class=muted>({e(where)})</span>"
        + tick(any(names_match(name, accepted) for accepted in gold_names))
        for name, where in first_place.items()
    ]
    expected = {social_key(url) for url in gold_social}
    social = [link(p.url) + tick(social_key(p.url) in expected) for p in ev.social_links]
    data, contacts, page = ev.structured, ev.contacts, ev.page
    profile = f"{page.platform}: {page.profile_name or 'no name'}" if page.platform else ""
    phones = [
        f"{e(phone)} <span class=muted>({e(', '.join(contacts.phone_places.get(phone, ())))})</span>"
        for phone in contacts.phones
    ]
    return rows(
        [
            ("Names", lines(names)),
            ("Profile", e(profile)),
            ("Own website", link(page.own_website) if page.own_website else ""),
            ("Phones", lines(phones)),
            ("Emails", e(", ".join(contacts.emails))),
            ("Address (schema)", e(data.address.text) if data.address else ""),
            ("Postcodes", e(", ".join(contacts.postcodes))),
            ("Countries", e(", ".join(ev.countries))),
            ("Copyright", e(contacts.copyright_line or "")),
            ("Schema types", e(", ".join(data.types))),
            ("Social links", lines(social)),
            ("Contact pages", lines(link(url) for url in ev.contact_pages)),
        ]
    )


def _evidence(site: ReportSite, ev: Evidence, page: Path) -> str:
    gold = site.gold
    shot = file_url(site.screenshot, page) if site.screenshot else None
    gold_logos = gold.logo_urls if gold and isinstance(gold.logo_urls, tuple) else ()
    accepted = {image_key(url) for url in gold_logos}
    logos = "".join(_logo(c, shot, accepted) for c in ev.logo_candidates)
    regions = (("header", ev.text.header), ("main", ev.text.main), ("footer", ev.text.footer))
    text = "\n\n".join(f"[{name}]\n{value}" for name, value in regions if value)
    screenshot = (
        f'<a href="{e(shot)}" target="_blank"><img src="{e(shot)}" alt="Screenshot of the first screen" loading="lazy"></a>'
        if shot
        else "<span class=muted>no screenshot</span>"
    )
    return f"""
  <div class="grid">
    <div class="shot">{screenshot}</div>
    <div><table class="facts">{_facts(ev, gold)}</table></div>
  </div>
  <h3>Logo candidates, best first</h3>
  <div class="logos">{logos or "<span class=muted>none</span>"}</div>
  {_checks(site)}
  <details><summary>Page text</summary><pre>{e(text) or "(none)"}</pre></details>"""


def site_card(site: ReportSite, page: Path, root: Path | None = None) -> str:
    """One site's card. `root` is the folder the result's files, like the logo, are in."""
    ev, result = site.evidence, site.result
    misses = sum(not c.found for c in site.checks)
    misses += sum(score.verdict in _MISSES for score in site.scores)
    badges = [ev.page.kind.value.replace("_", " ")] if ev else []
    badges += [f"status {site.status_code}"] if site.status_code is not None else []
    badges += [site.loaded_with] if site.loaded_with else []
    badges_html = "".join(f'<span class="badge">{e(badge)}</span>' for badge in badges)
    if result is not None and result.error:
        badges_html += '<span class="badge bad">failed</span>'
    if site.checks or site.scores:
        badges_html += f'<span class="badge {"bad" if misses else "good"}">{misses} missed</span>'
    answers = (
        f"<h3>Answers</h3>"
        f"{answers_table(result, site.scores, page, root or page.parent, site.labels)}"
        if result is not None
        else ""
    )
    unchecked = (
        f' data-unchecked="{sum(label is None for label in site.labels.values())}"'
        if site.labels is not None
        else ""
    )
    if ev is not None:
        details = _evidence(site, ev, page)
    else:
        details = (
            f'<p class="miss">{e(result.error if result and result.error else "no evidence")}</p>'
        )
    return f"""
<section class="card site" data-url="{e(site.url.lower())}" data-misses="{misses}"{unchecked}>
  <div class="site-head"><h2>{link(site.url)}</h2>{badges_html}</div>
  {answers}
  {details}
</section>"""
