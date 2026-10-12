"""Tests for keeping a run's files in a local folder."""

import asyncio
from pathlib import Path

import pytest

from bi2.adapters.local.files import LocalFiles


def test_files_are_saved_and_read_under_the_output_folder(tmp_path: Path) -> None:
    files = LocalFiles(tmp_path)
    saved = asyncio.run(files.save("example-cafe.ca/logo.png", b"logo"))
    assert saved == "example-cafe.ca/logo.png"
    assert (tmp_path / "example-cafe.ca" / "logo.png").read_bytes() == b"logo"
    assert asyncio.run(files.read(saved)) == b"logo"


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "a/../../b.txt", ""])
def test_paths_cant_reach_outside_the_output_folder(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError, match="isn't a path inside the output folder"):
        asyncio.run(LocalFiles(tmp_path).save(path, b"x"))
