"""Helpers for comparing names and phrases that are written in different ways."""

import re
import unicodedata
from functools import cache
from importlib.resources import files

_SPACES = re.compile(r"\s+")
_NOT_WORD = re.compile(r"[^\w\s]")


def clean_space(text: str) -> str:
    """Collapse runs of whitespace into single spaces and trim the ends."""
    return _SPACES.sub(" ", text).strip()


def fold(text: str) -> str:
    """Lowercase, remove accents and collapse whitespace, for comparing text."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return clean_space(without_accents.casefold())


@cache
def _legal_suffixes() -> frozenset[str]:
    text = files("bi2.data").joinpath("legal_suffixes.txt").read_text(encoding="utf-8")
    return frozenset(
        fold(line).replace(".", "")
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    )


def normalize_company_name(name: str) -> str:
    """Reduce a company name to a key for comparing: folded, without punctuation, without a
    leading "the" and without legal suffixes such as Inc. or Ltd."""
    text = fold(name).replace(".", "").replace("&", " and ")
    words = _NOT_WORD.sub(" ", text).split()
    if words[:1] == ["the"]:
        words = words[1:]
    suffixes = _legal_suffixes()
    while words and words[-1] in suffixes:
        words = words[:-1]
    return " ".join(words)


def names_match(a: str, b: str) -> bool:
    """Whether two company names are the same once normalized."""
    key = normalize_company_name(a)
    return bool(key) and key == normalize_company_name(b)
