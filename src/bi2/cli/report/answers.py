"""The report's table of final answers: each field's value, how it was decided and, against a
gold set, whether it's right."""

from pathlib import Path
from typing import Any, Final

from bi2.cli.report.html import e, file_url, lines, link
from bi2.core.models import FieldResult, SiteResult, Status
from bi2.evaluation.scoring import FieldScore, Verdict

_LABELS: Final = {
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


def answers_table(
    result: SiteResult, scores: tuple[FieldScore, ...], page: Path, root: Path
) -> str:
    """The table of a site's final answers. `root` is the folder the result's files are in."""
    by_field = {score.field: score for score in scores}
    body = "".join(
        f"<tr><th>{e(_LABELS.get(name, name))}</th><td>{_value(name, field, page, root)}</td>"
        f'<td><span class="status {field.status.value}">{_STATUS[field.status]}</span></td>'
        f"<td>{'' if field.confidence is None else f'{field.confidence:.2f}'}</td>"
        f"<td>{_why(field)}</td><td>{_gold(by_field.get(name))}</td></tr>"
        for name, field in result.field_results.items()
    )
    head = "<tr><th>Field</th><th>Answer</th><th>Status</th><th>Sure</th><th>Why</th><th>Gold</th></tr>"
    return f'<table class="answers">{head}{body}</table>'
