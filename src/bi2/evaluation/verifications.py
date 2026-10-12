"""Answers a person checked on the review page, with their notes.

They're kept in eval/verifications.jsonl, one check per line, newest last. A check is about one
answer: when a later run gives a different answer for the same field, the old check doesn't
apply to it. Answers are compared the forgiving way the scoring compares them, so "Example Cafe
Ltd." and "EXAMPLE CAFE" are the same answer.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from bi2.core.models import FieldResult, Status
from bi2.core.text import fold, normalize_company_name
from bi2.core.urls import image_key, social_key
from bi2.evaluation.gold import site_key

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
