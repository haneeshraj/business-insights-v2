"""The checker: a second look at answers already marked sure, to catch rules that start to slip.

The accuracy plan sends a share of the sure answers, 1 in 20 by default, to a model that
didn't give them, with the evidence they rest on, and asks one yes-or-no question: is this
right? Its agreement with people's checks is measured first (`bi2 eval check`), since a checker
is only worth trusting when it agrees with them almost every time.
"""

import hashlib
import re
from typing import Any, Final

from bi2.core.asking import Ask, Question, YesNo
from bi2.core.context import RunContext
from bi2.core.models import Evidence, SiteResult, Status
from bi2.core.urls import registrable_domain
from bi2.resolvers.asking import around, ask_decider, digits_pattern, site_lines
from bi2.resolvers.mcc import mcc_codes

_VERSION: Final = "1"
CHECKED_FIELDS: Final = ("company_name", "mcc", "address", "phone", "email")


def sampled(url: str, field: str, share: float) -> bool:
    """Whether an answer is in the checked sample: the same answers every run, by a hash of
    the site and the field, so reruns check the same ones."""
    digest = hashlib.sha256(f"{url}|{field}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32 < share


def _text(ev: Evidence) -> str:
    parts = (
        ev.text.header,
        ev.text.main,
        ev.text.footer,
        ev.contact_page.text if ev.contact_page else "",
    )
    return "\n".join(part for part in parts if part)


def _question(field: str, value: Any, ev: Evidence) -> tuple[str, str] | None:
    """The state and the question that check one answer, or None for an answer this checker
    doesn't check."""
    lines = site_lines(ev)
    text = _text(ev)
    domain = registrable_domain(ev.page.final_url or ev.page.url)
    match field:
        case "company_name":
            lines += [
                f"Top of the page: {ev.text.header[:300]}",
                f"Footer: {ev.text.footer[-300:]}",
            ]
            return "\n".join(
                lines
            ), f'Is "{value}" the name of the business that {domain} belongs to?'
        case "mcc":
            code = value["code"]
            lines.append(f"Main text: {ev.text.main[:1000]}")
            question = f"Is merchant category {code}, {mcc_codes().get(code, '')}, right for this business?"
            return "\n".join(lines), question
        case "address":
            lines.append(f"Footer: {ev.text.footer[-800:]}")
            question = f'Is "{value["text"]}" the address of this business\'s head office or only location?'
            return "\n".join(lines), question
        case "phone":
            lines += [f'shown as: "{s}"' for s in around(text, digits_pattern(value))]
            return "\n".join(lines), f"Is {value} this business's own main phone number?"
        case "email":
            lines += [f'shown as: "{s}"' for s in around(text, re.escape(value))]
            return "\n".join(lines), f"Is {value} this business's general contact email address?"
    return None


async def check_answers(
    result: SiteResult, ev: Evidence, ctx: RunContext, *, share: float = 0.05
) -> dict[str, float]:
    """The checker's probability that each sampled sure answer is right, by field."""
    questions: dict[str, Question] = {}
    states: list[str] = []
    for field in CHECKED_FIELDS:
        answer = result.field_results[field]
        if answer.status is not Status.OK or not sampled(result.page.url, field, share):
            continue
        asked = _question(field, answer.model_dump(mode="json")["value"], ev)
        if asked is not None:
            states.append(f"[{field}]\n{asked[0]}")
            questions[field] = YesNo(instructions=f"From the [{field}] evidence: {asked[1]}")
    if not questions:
        return {}
    ask = Ask(task="check", version=_VERSION, state="\n\n".join(states), questions=questions)
    decision = await ask_decider(ask, ctx)
    if isinstance(decision, str):
        return {}
    return {field: decision.agreed(field).probability for field in questions}
