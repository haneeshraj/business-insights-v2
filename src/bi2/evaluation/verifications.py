"""Answers a person checked on the review page, with their notes.

They're kept in eval/verifications.jsonl, one check per line, newest last. A check is about one
answer: when a later run gives a different answer for the same field, the old check doesn't
apply to it. Answers are compared the forgiving way the scoring compares them, so "Example Cafe
Ltd." and "EXAMPLE CAFE" are the same answer.

The right answers people confirm, or give with an answer they mark wrong, also make an answer
key in the gold set's form (`answers_from_checks`), so a later run's different answer can still
be scored.
"""

import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from bi2.core.models import FieldResult, Status
from bi2.core.text import fold, normalize_company_name
from bi2.core.urls import image_key, social_key
from bi2.evaluation.gold import GoldSite, site_key

type CheckKey = tuple[str, str, str]  # the site, the field and the answer


def answer_key(field: str, answer: FieldResult[Any]) -> str:
    """An answer written so that the same answer matches on another run; empty for none."""
    value = answer.value
    if value is None:
        return ""
    if field == "logo":
        return image_key(value.url) if value.url else str(value.image_file or "")
    if field == "social_links":
        return " ".join(sorted(social_key(profile.url) for profile in value))
    if field == "company_name":
        return normalize_company_name(value)
    if field == "mcc":
        return str(value.code)
    if field == "address":
        return fold(value.text)
    if field == "email":
        return str(value).lower()
    return str(value)


def answer_text(field: str, answer: FieldResult[Any]) -> str:
    """An answer as the review page shows it, so the checks file can be read on its own."""
    value = answer.value
    if value is None:
        return ""
    if field == "logo":
        return str(value.url or value.image_file)
    if field == "social_links":
        return " ".join(profile.url for profile in value)
    if field == "mcc":
        return f"{value.code} {value.description}"
    if field == "address":
        return str(value.text)
    return str(value)


class Verification(BaseModel):
    """One answer a person checked."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    site: str
    field: str
    answer: str  # the answer's key; empty when v2 found nothing
    shown: str = ""  # the answer as the page showed it, for reading the file
    verdict: Literal["right", "wrong"]
    note: str = ""  # what the person saw, for whoever improves the rules next
    # The right answer, given with one marked wrong: a name, a phone number in E.164 format,
    # a lowercase email address, the logo's address, or profile addresses separated by spaces. A logo with no address of
    # its own is written as its candidate number, like "#2".
    correct: str = ""
    status: Status  # how v2 had marked the answer
    confidence: float | None = None
    checked_at: AwareDatetime

    @property
    def key(self) -> CheckKey:
        return site_key(self.site), self.field, self.answer


def load_verifications(path: Path) -> dict[CheckKey, Verification]:
    """Every check in the file, keeping the newest for each answer."""
    if not path.exists():
        return {}
    checks: dict[CheckKey, Verification] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            check = Verification.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(f"{path.name}, line {number}: {exc}") from exc
        checks[check.key] = check
    return checks


def add_verification(path: Path, check: Verification) -> None:
    """Add a check to the end of the file. Earlier checks of the same answer stay, as history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(check.model_dump_json() + "\n")


# The fields a check can give the right answer for, and the gold-set list each one fills.
_GOLD_FIELDS: Final = {
    "company_name": "company_names",
    "logo": "logo_urls",
    "phone": "phones",
    "email": "emails",
    "social_links": "social_links",
}
_E164: Final = re.compile(r"^\+[1-9]\d{6,14}$")
_EMAIL: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,24}$")


def _usable(field: str, value: str) -> bool:
    """Whether a value fits the gold set: addresses for logos and profiles, E.164 for phones."""
    if field in ("logo", "social_links"):
        return value.startswith(("http://", "https://"))
    if field == "phone":
        return bool(_E164.match(value))
    if field == "email":
        return bool(_EMAIL.match(value))
    return bool(value.strip())


def answers_from_checks(checks: Iterable[Verification]) -> dict[str, GoldSite]:
    """The right answers people confirmed or gave, by site, in the gold set's form.

    An answer marked right counts, and so does the right answer given with one marked wrong.
    "The site has none" marked right makes the field "none". For social links, the latest right
    answer is the whole list, since a right answer must find every profile in it."""
    values: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    nothing: dict[str, set[str]] = defaultdict(set)
    urls: dict[str, str] = {}
    for check in sorted(checks, key=lambda check: check.checked_at):
        if check.field not in _GOLD_FIELDS:
            continue
        key = site_key(check.site)
        urls.setdefault(key, check.site)
        if check.verdict == "right" and check.answer == "":
            nothing[key].add(check.field)
            continue
        given = check.shown if check.verdict == "right" else check.correct
        if check.field == "social_links":
            profiles = [value for value in given.split() if _usable(check.field, value)]
            if profiles:
                values[key][check.field] = profiles
        elif _usable(check.field, given):
            values[key][check.field].append(given)
    sites = {}
    for key, url in urls.items():
        answers: dict[str, Any] = {}
        for field, gold_field in _GOLD_FIELDS.items():
            if values[key].get(field):
                answers[gold_field] = tuple(dict.fromkeys(values[key][field]))
            elif field in nothing[key] and field != "company_name":
                answers[gold_field] = "none"
        if answers:
            sites[key] = GoldSite.model_validate({"url": url, "category": "checked", **answers})
    return sites
