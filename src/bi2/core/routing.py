"""Which answers v2 keeps without AI, and which it sends on to the next step.

The decision is learned from checked answers: those a person marked right or wrong on the review
page, and those the gold set can score. Each field's checked answers are grouped by confidence.
A group is kept when enough of its checked answers were right; a group with too few checked
answers falls back to the accept threshold. `bi2 review` rebuilds data/routing.toml every time
an answer is checked, and every run reads it.
"""

import tomllib
from functools import cache
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, Field


class Group(BaseModel):
    """The checked answers of one field at one confidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confidence: float = Field(ge=0, le=1)
    checked: int = Field(ge=0)
    right: int = Field(ge=0)


class Routing(BaseModel):
    """The learned decision. With no groups, every answer goes by the accept threshold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: float = Field(default=0.95, ge=0, le=1)  # share of a group that must have been right
    min_checked: int = Field(default=5, ge=1)  # checked answers before a group's record counts
    groups: dict[str, tuple[Group, ...]] = Field(default_factory=dict)  # by field

    def group(self, field: str, confidence: float) -> Group | None:
        """The checked answers like this one: the same field, at the same confidence."""
        return next(
            (g for g in self.groups.get(field, ()) if abs(g.confidence - confidence) < 0.005),
            None,
        )

    def decide(self, field: str, confidence: float, accept: float) -> tuple[bool, str]:
        """Whether to keep an answer without AI, and why."""
        group = self.group(field, confidence)
        if group is not None and group.checked >= self.min_checked:
            record = f"{group.right} of {group.checked}"
            if group.right / group.checked >= self.target:
                return True, f"answers like this were right {record} times"
            return False, f"answers like this were right only {record} times"
        if confidence >= accept:
            return True, ""
        return False, f"not sure enough: {confidence:.2f}, below {accept:.2f}"

    def to_toml(self, version: str) -> str:
        """The decision as data/routing.toml holds it."""
        lines = [
            "# Which answers v2 keeps without AI, learned from checked answers. Rebuilt by",
            "# `bi2 review` every time an answer is checked; see bi2/core/routing.py.",
            "",
            f'version = "{version}"',
            f"target = {self.target}",
            f"min_checked = {self.min_checked}",
        ]
        for field, groups in self.groups.items():
            for group in groups:
                lines += [
                    "",
                    f"[[groups.{field}]]",
                    f"confidence = {group.confidence}",
                    f"checked = {group.checked}",
                    f"right = {group.right}",
                ]
        return "\n".join(lines) + "\n"


@cache
def load_routing() -> Routing:
    """The decision shipped in data/routing.toml, or an empty one before anything's learned."""
    path = files("bi2.data").joinpath("routing.toml")
    if not path.is_file():
        return Routing()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    data.pop("version", None)
    return Routing.model_validate(data)
