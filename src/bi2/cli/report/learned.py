"""The review page's summary of what the checks teach: for each field, how many answers are in
each of the four groups and how often answers were right at each confidence, and the notes
you've written."""

from collections import Counter

from bi2.cli.report.answers import FIELD_LABELS
from bi2.cli.report.html import e, link
from bi2.core.models import FIELD_NAMES
from bi2.evaluation.learning import Label, Outcome, Record, by_confidence, tally


def _in_field_order[T](by_field: dict[str, T]) -> list[tuple[str, T]]:
    return sorted(by_field.items(), key=lambda item: FIELD_NAMES.index(item[0]))


def _groups(by_field: dict[str, Counter[Outcome]]) -> str:
    head = "".join(
        f"<th>{e(outcome.capitalize())}<br><span class=muted>{e(outcome.term)}</span></th>"
        for outcome in Outcome
    )
    body = "".join(
        f"<tr><th>{e(FIELD_LABELS[field])}</th><td>{counts.total()}</td>"
        + "".join(f"<td>{counts[outcome]}</td>" for outcome in Outcome)
        + "</tr>"
        for field, counts in _in_field_order(by_field)
    )
    return f'<table class="groups"><tr><th>Field</th><th>Checked</th>{head}</tr>{body}</table>'


def _records(records: dict[str, tuple[Record, ...]]) -> str:
    body = "".join(
        f"<tr><th>{e(FIELD_LABELS[field]) if index == 0 else ''}</th>"
        f'<td>{record.confidence:.2f}</td><td class="count">{record.right} of {record.checked}</td>'
        f'<td class="share"><div class="bar"><span style="width:{record.right / record.checked:.0%}">'
        f"</span></div>{record.right / record.checked:.0%}</td></tr>"
        for field, levels in _in_field_order(records)
        for index, record in enumerate(levels)
    )
    return (
        f'<table class="records"><tr><th>Field</th><th>Sure</th><th>Right</th><th>Share</th></tr>'
        f"{body}</table>"
    )


def _notes(labels: list[Label]) -> str:
    noted = [label for label in labels if label.by == "you" and (label.note or label.correct)]
    if not noted:
        return "<p class=muted>None yet. A note says what you saw, so the rules can learn it.</p>"
    body = "".join(
        f"<tr><td>{link(label.site)}</td><td>{e(FIELD_LABELS[label.field])}</td>"
        f"<td>{'right' if label.right else 'wrong'}</td><td>{e(label.correct)}</td>"
        f"<td>{e(label.note)}</td></tr>"
        for label in noted
    )
    head = "<th>Site</th><th>Field</th><th>Your check</th><th>Right answer</th><th>Note</th>"
    return f'<table class="notes"><tr>{head}</tr>{body}</table>'


def learned_section(labels: list[Label], answers: int) -> str:
    """The summary, from the labels of every checked answer. `answers` is how many answers
    could be checked."""
    by = Counter(label.by for label in labels)
    yours = by["you"] + by["your answers"]
    drafted = by["draft"] + by["drafted answers"]
    from_drafts = (
        f", {drafted} by drafted checks that no person has confirmed yet" if drafted else ""
    )
    groups = _groups(tally(labels)) if labels else ""
    return f"""<section class="card" id="learned">
  <h2>What the checks teach</h2>
  <p>{len(labels)} of {answers} answers checked: {yours} by you{from_drafts}, and
  {by["gold set"]} by the gold set. Your checks count first, then drafts, then the gold set.</p>
  <h3>The four groups</h3>
  <p class=muted>Kept: v2 marked the answer ok. Sent on: it needs review, or nothing was found;
  that's where an AI step would come in.</p>
  {groups}
  <h3>How often answers were right, by how sure v2 was</h3>
  {_records(by_confidence(labels))}
  <h3>Your notes</h3>
  {_notes(labels)}
</section>"""
