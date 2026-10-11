"""Checks for conventions in docs/codebase.md that the linters don't cover."""

import importlib
import pkgutil

import bi2

GENERIC_MODULE_NAMES = {"utils", "helpers", "misc"}


def _all_modules() -> list[pkgutil.ModuleInfo]:
    return list(pkgutil.walk_packages(bi2.__path__, prefix="bi2."))


def test_every_package_says_what_belongs_in_it() -> None:
    undocumented = [
        info.name
        for info in _all_modules()
        if info.ispkg and not (importlib.import_module(info.name).__doc__ or "").strip()
    ]
    assert undocumented == [], f"Add a docstring to each package's __init__.py: {undocumented}"


def test_modules_are_named_after_their_topic() -> None:
    generic = [
        info.name for info in _all_modules() if info.name.rsplit(".", 1)[-1] in GENERIC_MODULE_NAMES
    ]
    assert generic == [], f"Name these modules after their topic instead: {generic}"
