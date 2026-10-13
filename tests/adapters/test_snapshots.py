"""Tests for saving pages, reading them back, and serving them to a run of saved pages."""

import asyncio
from pathlib import Path

import pytest

from bi2.adapters.local.snapshots import (
    SavedPages,
    load_snapshot,
    save_extra_page,
    save_snapshot,
    saved_folders,
)
from bi2.core.errors import FetchError
from tests.factories import page_snapshot

URL = "https://example-cafe.ca/"


def test_a_saved_page_reads_back_the_same(tmp_path: Path) -> None:
    copies = {f"{URL}logo.png": bytes(range(256))}  # every byte value
    snapshot = page_snapshot("<html></html>", image_copies=copies, screenshot=b"\xff\xd8")
    loaded = load_snapshot(save_snapshot(snapshot, tmp_path))
    assert loaded.image_copies == copies
    assert loaded == snapshot


def test_a_run_of_saved_pages_reads_a_sites_contact_page(tmp_path: Path) -> None:
    site = save_snapshot(page_snapshot("<html>home</html>"), tmp_path)
    contact = page_snapshot("<html>Call us</html>", url=f"{URL}contact-us")
    save_extra_page(contact, site)
    assert saved_folders(tmp_path) == [site]  # the contact page isn't a site of its own
    pages = SavedPages(tmp_path)
    assert asyncio.run(pages.fetch(f"{URL}contact-us")).html == "<html>Call us</html>"
    with pytest.raises(FetchError, match="wasn't saved"):
        asyncio.run(pages.fetch(f"{URL}about"))
