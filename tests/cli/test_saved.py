"""Tests for saving pages and reading them back."""

from pathlib import Path

from bi2.cli.dev.saved import load_snapshot, save_snapshot
from tests.factories import page_snapshot


def test_a_saved_page_reads_back_the_same(tmp_path: Path) -> None:
    copies = {"https://example-cafe.ca/logo.png": bytes(range(256))}  # every byte value
    snapshot = page_snapshot("<html></html>", image_copies=copies, screenshot=b"\xff\xd8")
    loaded = load_snapshot(save_snapshot(snapshot, tmp_path))
    assert loaded.image_copies == copies
    assert loaded == snapshot
