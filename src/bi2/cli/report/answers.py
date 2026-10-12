"""The report's table of final answers: each field's value, how it was decided and, against a
gold set, whether it's right. On the review page each answer also gets your check: right or
wrong, with a note."""

from pathlib import Path
from typing import Any, Final

from bi2.cli.report.html import e, file_url, lines, link
from bi2.core.models import FieldResult, SiteResult, Status
from bi2.evaluation.learning import Label
from bi2.evaluation.scoring import FieldScore, Verdict

FIELD_LABELS: Final = {
    "company_name": "Name",
    "logo": "Logo",
    "mcc": "MCC",
    "address": "Address",
    "phone": "Phone",
    "social_links": "Social links",
}
_STATUS: Final = {
    Status.OK: "ok",
    Status.NEEDS_REVIEW: "needs review",
    Status.NOT_FOUND: "not found",
    Status.ERROR: "error",
}


def _value(name: str, field: FieldResult[Any], page: Path, root: Path) -> str:
    value = field.value
    if value is None:
        return "<span class=muted>&mdash;</span>"
    if name == "logo":
        parts = []
        if value.image_file:
            parts.append(
                f'<img class="answer-logo" src="{e(file_url(root / value.image_file, page))}" alt="">'
            )
        if value.url:
            parts.append(link(value.url, value.url.rsplit("/", 1)[-1][:50] or value.url))
        return "<br>".join(parts)
    if name == "social_links":
        return lines(link(profile.url) for profile in value)
    if name == "mcc":
        return e(f"{value.code} {value.description}")
    if name == "address":
        return e(value.text)
    return e(value)


def _why(field: FieldResult[Any]) -> str:
    if field.source:
        return e(field.source)
    detail = next((step.detail for step in reversed(field.steps) if step.detail), "")
    return f"<span class=muted>{e(detail)}</span>"


def _gold(score: FieldScore | None) -> str:
    if score is None or score.verdict is Verdict.NOT_SCORED:
        return ""
    if score.verdict is Verdict.CORRECT:
        return "<span class=ok>&check;</span>"
    wanted = "gold set says none" if score.verdict is Verdict.UNEXPECTED else score.expected
    return f"<span class=miss>&cross;</span> <span class=muted>{e(wanted)}</span>"


def label_html(label: Label | None) -> str:
    """Who checked an answer, what they said, and which of the four groups that puts it in."""
    if label is None:
        return "<span class=muted>not checked yet</span>"
    outcome = label.outcome
    short = "".join(word[0] for word in outcome.term.split())  # "tp" for true positive
    who = "You" if label.by == "you" else "Gold set"
    return (
        f'<span class="by">{who}: {"right" if label.right else "wrong"}</span> '
        f'<span class="group {short}" title="{e(outcome.term)}">{e(outcome)}</span>'
    )


def _check(site: str, field: str, label: Label | None, *, found: bool) -> str:
    """Your check of one answer: right or wrong, a note, and what's known about it so far.
    When v2 found nothing, right means there's nothing to find."""
    yours = label.right if label is not None and label.by == "you" else None
    note = label.note if label is not None and label.by == "you" else ""
    pressed = {"right": yours is True, "wrong": yours is False}
    buttons = "".join(
        f'<button type="button" data-verdict="{verdict}" aria-pressed="{str(on).lower()}">'
        f"{verdict.capitalize()}</button>"
        for verdict, on in pressed.items()
    )
    return (
        f'<td class="check" data-site="{e(site)}" data-field="{e(field)}">{buttons}'
        f'<input class="note" type="text" maxlength="1000" value="{e(note)}" '
        f'placeholder="{"Note: what you saw" if found else "Right means there is none to find"}" '
        f'aria-label="Note">'
        f'<div class="label">{label_html(label)}</div></td>'
    )


def answers_table(
    result: SiteResult,
    scores: tuple[FieldScore, ...],
    page: Path,
    root: Path,
    labels: dict[str, Label | None] | None = None,
) -> str:
    """The table of a site's final answers. `root` is the folder the result's files are in.
    With `labels`, the answers that can be checked get your check: those are its keys, and
    each value is what's known so far, or None when no one has checked it."""
    by_field = {score.field: score for score in scores}
    rows = []
    for name, field in result.field_results.items():
        row = (
            f"<tr><th>{e(FIELD_LABELS.get(name, name))}</th><td>{_value(name, field, page, root)}</td>"
            f'<td><span class="status {field.status.value}">{_STATUS[field.status]}</span></td>'
            f"<td>{'' if field.confidence is None else f'{field.confidence:.2f}'}</td>"
            f"<td>{_why(field)}</td><td>{_gold(by_field.get(name))}</td>"
        )
        if labels is not None:
            row += (
                _check(result.page.url, name, labels[name], found=field.value is not None)
                if name in labels
                else "<td></td>"
            )
        rows.append(row + "</tr>")
    head = "<tr><th>Field</th><th>Answer</th><th>Status</th><th>Sure</th><th>Why</th><th>Gold</th>"
    head += "<th>Your check</th></tr>" if labels is not None else "</tr>"
    return f'<table class="answers">{head}{"".join(rows)}</table>'
