"""The interactive session's `/` commands. Each is a handler that takes the session's results
and the command's words, and returns what to show; none runs the pipeline itself."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Final

from rich.console import RenderableType
from rich.table import Table

from bi2.cli.output import results_csv
from bi2.core.models import FIELD_NAMES, SiteResult
from bi2.core.urls import registrable_domain

type Results = dict[str, SiteResult]
type Handler = Callable[[Results, list[str]], RenderableType]

HELP: Final = """\
Paste one or more website addresses to analyze them, or a command:
  /show <site>           every field with its value, status, confidence and source
  /why <site> <field>    how one field was decided: every step, why it passed on, its cost
  /export csv|json       save the session's results in bi2-results/session
  /keys                  which keys are set, with all but their last four characters hidden
  /help                  this help
  /quit                  leave (or Ctrl+D)"""


def _find(results: Results, site: str) -> SiteResult | None:
    """A result by its address or its domain, like "bellwoodsbrewery.com"."""
    wanted = registrable_domain(site if "://" in site else f"https://{site}")
    return next(
        (r for url, r in results.items() if url == site or registrable_domain(url) == wanted),
        None,
    )


def _value(field: str, result: SiteResult) -> str:
    value = result.model_dump(mode="json")[field]["value"]
    if value is None:
        return ""
    if field == "mcc":
        return f"{value['code']} {value['description']}"
    if field == "address":
        point = value.get("coordinates")
        at = f" ({point['latitude']:.4f}, {point['longitude']:.4f})" if point else ""
        return f"{value['text']}{at}"
    if field == "logo":
        return str(value.get("url") or value.get("image_file") or "")
    if field == "social_links":
        return " ".join(profile["url"] for profile in value)
    return str(value)


def show(results: Results, words: list[str]) -> RenderableType:
    """Every field of one site."""
    if not words:
        return "Which site? Like: /show bellwoodsbrewery.com"
    result = _find(results, words[0])
    if result is None:
        return f"{words[0]} hasn't been analyzed in this session."
    table = Table(title=result.page.url)
    for column in ("Field", "Value", "Status", "Confidence", "Source"):
        table.add_column(column, overflow="fold")
    for field in FIELD_NAMES:
        answer = result.field_results[field]
        confidence = "" if answer.confidence is None else f"{answer.confidence:.2f}"
        table.add_row(
            field, _value(field, result), answer.status.value, confidence, answer.source or ""
        )
    return table


def why(results: Results, words: list[str]) -> RenderableType:
    """The audit trail of one field."""
    if len(words) < 2 or words[1] not in FIELD_NAMES:
        return f"Like: /why bellwoodsbrewery.com mcc. The fields: {', '.join(FIELD_NAMES)}"
    result = _find(results, words[0])
    if result is None:
        return f"{words[0]} hasn't been analyzed in this session."
    table = Table(title=f"{words[1]} for {result.page.url}")
    for column in ("Step", "Outcome", "Confidence", "Cost", "Why"):
        table.add_column(column, overflow="fold")
    for step in result.field_results[words[1]].steps:
        confidence = "" if step.confidence is None else f"{step.confidence:.2f}"
        cost = f"${step.cost.usd:.5f}" if step.cost.model_calls else ""
        table.add_row(step.step, step.outcome.value, confidence, cost, step.detail)
    return table


def export(
    results: Results, words: list[str], *, folder: Path = Path("bi2-results/session")
) -> RenderableType:
    """The session's results, saved as CSV or JSON Lines."""
    kind = words[0] if words else "csv"
    if kind not in ("csv", "json"):
        return "Like: /export csv, or /export json"
    if not results:
        return "Nothing to export yet: paste a website address first."
    folder.mkdir(parents=True, exist_ok=True)
    if kind == "csv":
        path = folder / "results.csv"
        path.write_text(results_csv(list(results.values())), encoding="utf-8")
    else:
        path = folder / "results.jsonl"
        lines = (json.dumps(r.model_dump(mode="json")) for r in results.values())
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"Saved {len(results)} results to {path.resolve()}"


def keys(results: Results, words: list[str]) -> RenderableType:
    """Which keys are set, and where."""
    from bi2.cli.doctor import found_keys, hidden

    held, found = found_keys()
    lines = [
        f"{provider}: {hidden(key.get_secret_value())}, from the {where}"
        for provider, where in found.items()
        if (key := held.get(provider)) is not None
    ]
    return "\n".join(lines) or "No keys are set. Run `bi2 config` to choose a provider."


def help_text(results: Results, words: list[str]) -> RenderableType:
    """The session's help."""
    return HELP


COMMANDS: Final[dict[str, Handler]] = {
    "/show": show,
    "/why": why,
    "/export": export,
    "/keys": keys,
    "/help": help_text,
}
