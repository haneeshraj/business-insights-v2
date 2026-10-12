"""The HTML report `bi2 dev evidence` writes, for looking through every site's evidence in a
browser: what was found, the logo candidates as pictures, and how it compares with the gold set.

Everything a page supplied is escaped before it's written, since it comes from other sites.
"""

import os
from collections.abc import Iterable
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import NamedTuple

from bi2.core.models import Box, Evidence, LogoCandidate
from bi2.core.text import names_match
from bi2.core.urls import image_key, social_key
from bi2.evaluation.coverage import FieldCoverage
from bi2.evaluation.gold import ExpectedAddress, GoldSite
from bi2.evidence.names import name_candidates

# The screenshot is the first screen at this size; boxes inside it can be cropped out of it.
_SCREEN_WIDTH, _SCREEN_HEIGHT = 1280, 800
_PREVIEW_WIDTH, _PREVIEW_HEIGHT = 156, 72
_DOT = " \N{MIDDLE DOT} "


class ReportSite(NamedTuple):
    """One site in the report."""

    evidence: Evidence
    status_code: int | None
    loaded_with: str
    screenshot: Path | None
    gold: GoldSite | None = None
    checks: tuple[FieldCoverage, ...] = ()


def _e(text: object) -> str:
    return escape(str(text), quote=True)


def _link(url: str, text: str | None = None) -> str:
    return f'<a href="{_e(url)}" target="_blank" rel="noopener noreferrer">{_e(text or url)}</a>'


def _file_url(path: Path, page: Path) -> str:
    """How the report points to a saved file: relative when possible, so the folder can move."""
    try:
        return Path(os.path.relpath(path, page.parent)).as_posix()
    except ValueError:  # on another drive
        return path.resolve().as_uri()


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
    return f'<div class="crop" style="{_e(style)}"></div>'


def _logo(candidate: LogoCandidate, screenshot: str | None, accepted: set[str]) -> str:
    """One logo candidate: what it looked like on the page, and why it ranked where it did."""
    preview = _crop(candidate.box, screenshot) if candidate.box and screenshot else None
    if preview is None and candidate.url:
        preview = (
            f'<img src="{_e(candidate.url)}" alt="" loading="lazy" referrerpolicy="no-referrer">'
        )
    matches = candidate.url is not None and image_key(candidate.url) in accepted
    notes: list[str] = [candidate.kind]
    notes += ["header"] if candidate.in_header else []
    notes += ["links home"] if candidate.links_home else []
    label = candidate.alt or (candidate.url or "").rsplit("/", 1)[-1] or "inline image"
    gold = " <span class=ok>&check; gold</span>" if matches else ""
    return (
        f'<figure class="logo{" match" if matches else ""}">'
        f'<div class="preview">{preview or "<span class=muted>no preview</span>"}</div>'
        f"<figcaption><b>#{candidate.number}</b> {_e(_DOT.join(notes))}{gold}"
        f'<br><span class="muted">{_e(label[:60])}</span></figcaption></figure>'
    )


def _rows(rows: Iterable[tuple[str, str]]) -> str:
    return "".join(
        f"<tr><th>{_e(label)}</th><td>{value}</td></tr>" for label, value in rows if value
    )


def _list(values: Iterable[str]) -> str:
    return "<br>".join(values)


def _expected(check: str, gold: GoldSite) -> str:
    """What the gold set expects, for showing next to a check."""
    if check == "page_kind":
        return gold.page_kind.value + (f" ({gold.platform})" if gold.platform else "")
    if check == "company_name":
        return " | ".join(gold.company_names or ())
    if check.startswith("logo") and isinstance(gold.logo_urls, tuple):
        return _list(_link(url, url.rsplit("/", 1)[-1]) for url in gold.logo_urls)
    if check.startswith("address") and isinstance(gold.address, ExpectedAddress):
        parts = (gold.address.street, gold.address.city, gold.address.postal_code)
        return ", ".join(part for part in parts if part)
    if check.startswith("country") and isinstance(gold.address, ExpectedAddress):
        return gold.address.country or ""
    if check == "phone" and isinstance(gold.phones, tuple):
        return ", ".join(gold.phones)
    if check == "social_links" and isinstance(gold.social_links, tuple):
        return _list(_link(url) for url in gold.social_links)
    return ""


def _checks(site: ReportSite) -> str:
    if site.gold is None or not site.checks:
        return ""
    rows = "".join(
        f'<tr><td class="{"ok" if c.found else "miss"}">{"&check;" if c.found else "&cross;"}</td>'
        f"<td>{_e(c.check)}</td><td>{_e(c.where)}</td><td>{_expected(c.check, site.gold)}</td></tr>"
        for c in site.checks
    )
    head = "<tr><th></th><th>Gold check</th><th>Found in</th><th>Gold answer</th></tr>"
    return f'<table class="checks">{head}{rows}</table>'


def _tick(found: bool) -> str:
    return " <span class=ok>&check;</span>" if found else ""


def _facts(ev: Evidence, gold: GoldSite | None) -> str:
    """The evidence for one site, with a tick on each value the gold set accepts."""
    gold_names = (gold.company_names or ()) if gold else ()
    gold_social = gold.social_links if gold and isinstance(gold.social_links, tuple) else ()
    first_place: dict[str, str] = {}  # each name once, with the first place it was found
    for where, name in name_candidates(ev):
        first_place.setdefault(name, where)
    names = [
        f"{_e(name)} <span class=muted>({_e(where)})</span>"
        + _tick(any(names_match(name, accepted) for accepted in gold_names))
        for name, where in first_place.items()
    ]
    expected = {social_key(url) for url in gold_social}
    social = [_link(p.url) + _tick(social_key(p.url) in expected) for p in ev.social_links]
    data, contacts, page = ev.structured, ev.contacts, ev.page
    return _rows(
        [
            ("Names", _list(names)),
            (
                "Profile",
                _e(f"{page.platform}: {page.profile_name or 'no name'}") if page.platform else "",
            ),
            ("Own website", _link(page.own_website) if page.own_website else ""),
            ("Phones", _e(", ".join(contacts.phones))),
            ("Emails", _e(", ".join(contacts.emails))),
            ("Address (schema)", _e(data.address.text) if data.address else ""),
            ("Postcodes", _e(", ".join(contacts.postcodes))),
            ("Countries", _e(", ".join(ev.countries))),
            ("Copyright", _e(contacts.copyright_line or "")),
            ("Schema types", _e(", ".join(data.types))),
            ("Social links", _list(social)),
            ("Contact pages", _list(_link(url) for url in ev.contact_pages)),
        ]
    )


def _site(site: ReportSite, page: Path) -> str:
    """One site's card."""
    ev, gold = site.evidence, site.gold
    shot = _file_url(site.screenshot, page) if site.screenshot else None
    gold_logos = gold.logo_urls if gold and isinstance(gold.logo_urls, tuple) else ()
    accepted = {image_key(url) for url in gold_logos}
    misses = sum(not check.found for check in site.checks)
    badges = [ev.page.kind.value.replace("_", " "), f"status {site.status_code or '?'}"]
    badges += [site.loaded_with] if site.loaded_with else []
    badges_html = "".join(f'<span class="badge">{_e(badge)}</span>' for badge in badges)
    if site.checks:
        badges_html += f'<span class="badge {"bad" if misses else "good"}">{misses} missed</span>'
    logos = "".join(_logo(c, shot, accepted) for c in ev.logo_candidates)
    regions = (("header", ev.text.header), ("main", ev.text.main), ("footer", ev.text.footer))
    text = "\n\n".join(f"[{name}]\n{value}" for name, value in regions if value)
    screenshot = (
        f'<a href="{_e(shot)}" target="_blank"><img src="{_e(shot)}" alt="Screenshot of the first screen" loading="lazy"></a>'
        if shot
        else "<span class=muted>no screenshot</span>"
    )
    return f"""
<section class="card site" data-url="{_e(ev.page.url.lower())}" data-misses="{misses}">
  <div class="site-head"><h2>{_link(ev.page.url)}</h2>{badges_html}</div>
  <div class="grid">
    <div class="shot">{screenshot}</div>
    <div><table class="facts">{_facts(ev, site.gold)}</table></div>
  </div>
  <h3>Logo candidates, best first</h3>
  <div class="logos">{logos or "<span class=muted>none</span>"}</div>
  {_checks(site)}
  <details><summary>Page text</summary><pre>{_e(text) or "(none)"}</pre></details>
</section>"""


def _summary(summary: dict[str, tuple[int, int]]) -> str:
    rows = "".join(
        f'<tr><td>{_e(check)}</td><td class="count">{found} of {total}</td>'
        f'<td class="share"><div class="bar"><span style="width:{found / total:.0%}"></span></div>{found / total:.0%}</td></tr>'
        for check, (found, total) in summary.items()
    )
    return (
        '<section class="card"><h2>What the evidence already holds</h2>'
        f"<table><tr><th>Check</th><th>Found</th><th>Share</th></tr>{rows}</table></section>"
    )


def write_report(
    path: Path,
    sites: list[ReportSite],
    *,
    source: str,
    summary: dict[str, tuple[int, int]] | None = None,
) -> None:
    """Write the report as one HTML file that opens in any browser, with no server."""
    when = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    body = "".join(_site(site, path) for site in sites)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _PAGE.replace("{title}", "Evidence report")
        .replace("{subtitle}", _e(f"{len(sites)} pages from {source}, built {when}"))
        .replace("{summary}", _summary(summary) if summary else "")
        .replace("{sites}", body),
        encoding="utf-8",
    )


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root { --bg: #f6f6f8; --card: #fff; --text: #1d1d22; --muted: #6b6b78; --line: #e2e2e8;
        --good: #1a7f37; --bad: #c62828; --accent: #3355dd; color-scheme: light; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #121215; --card: #1b1b1f; --text: #ececf1; --muted: #9a9aa8; --line: #2c2c33;
          --good: #4ac26b; --bad: #ff6b6b; --accent: #7c9bff; color-scheme: dark; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
       font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1200px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 0; overflow-wrap: anywhere; }
h3 { font-size: 13px; margin: 16px 0 8px; color: var(--muted); font-weight: 600; }
a { color: var(--accent); }
.muted { color: var(--muted); }
.ok { color: var(--good); }
.miss { color: var(--bad); }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--line);
         vertical-align: top; overflow-wrap: anywhere; }
th { font-weight: 600; white-space: nowrap; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
        padding: 16px; margin: 16px 0; }
.site-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
.badge { font-size: 12px; padding: 1px 8px; border-radius: 99px; border: 1px solid var(--line);
         color: var(--muted); white-space: nowrap; }
.badge.bad { color: var(--bad); border-color: currentColor; }
.badge.good { color: var(--good); border-color: currentColor; }
.grid { display: grid; grid-template-columns: minmax(0, 340px) minmax(0, 1fr); gap: 16px; }
@media (max-width: 760px) { .grid { grid-template-columns: minmax(0, 1fr); } }
.shot img { width: 100%; border: 1px solid var(--line); border-radius: 6px; display: block; }
.facts th { width: 130px; color: var(--muted); }
.logos { display: flex; flex-wrap: wrap; gap: 8px; }
.logo { width: 172px; margin: 0; border: 1px solid var(--line); border-radius: 8px; padding: 6px;
        font-size: 12px; }
.logo.match { border-color: var(--good); box-shadow: inset 0 0 0 1px var(--good); }
.preview { height: 80px; display: flex; align-items: center; justify-content: center;
           border-radius: 4px; overflow: hidden;
           background: repeating-conic-gradient(#8881 0 25%, transparent 0 50%) 0 0 / 12px 12px; }
.preview img { max-width: 100%; max-height: 80px; }
figcaption { margin-top: 4px; overflow-wrap: anywhere; }
.checks { margin-top: 12px; }
.checks td:first-child { width: 24px; font-weight: 700; }
.share { width: 40%; }
.count { white-space: nowrap; }
.bar { display: inline-block; vertical-align: middle; width: 70%; height: 6px; margin-right: 8px;
       background: var(--line); border-radius: 3px; }
.bar span { display: block; height: 100%; background: var(--accent); border-radius: 3px; }
details { margin-top: 12px; }
summary { cursor: pointer; color: var(--muted); }
pre { white-space: pre-wrap; font: 12px/1.4 ui-monospace, Consolas, monospace; max-height: 260px;
      overflow: auto; background: var(--bg); padding: 8px; border-radius: 6px; }
.controls { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; margin: 16px 0 0; }
input[type=search] { padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px;
                     background: var(--card); color: var(--text); width: min(320px, 100%); }
</style>
</head>
<body>
<main>
<h1>{title}</h1>
<div class="muted">{subtitle}</div>
{summary}
<div class="controls">
  <input type="search" id="search" placeholder="Filter by address" aria-label="Filter by address">
  <label><input type="checkbox" id="misses"> Only sites that miss a gold answer</label>
</div>
{sites}
</main>
<script>
const search = document.getElementById("search");
const missesOnly = document.getElementById("misses");
function filter() {
  const words = search.value.trim().toLowerCase();
  for (const site of document.querySelectorAll(".site")) {
    site.hidden = !site.dataset.url.includes(words)
      || (missesOnly.checked && site.dataset.misses === "0");
  }
}
search.addEventListener("input", filter);
missesOnly.addEventListener("change", filter);
</script>
</body>
</html>
"""
