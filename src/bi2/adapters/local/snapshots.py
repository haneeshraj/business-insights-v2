"""Pages saved by `bi2 dev fetch`: writing them, reading them back, and serving them to a run in
place of a browser, so a run on saved pages sees the same pages every time.

Each site's folder holds its homepage, and a `pages` folder with the other pages read for it,
such as its contact page, each in a folder named after its address.
"""

import asyncio
import json
from pathlib import Path

from bi2.core.errors import FetchError
from bi2.core.models import PageSnapshot
from bi2.core.urls import site_folder

EXTRA_PAGES = "pages"  # the folder in a site's folder that holds its other pages


def save_page(snapshot: PageSnapshot, folder: Path) -> Path:
    """Save the screenshot, the HTML and everything else the browser captured in a folder. The
    browser's copies of images go in snapshot.json, in base64."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "page.html").write_text(snapshot.html, encoding="utf-8")
    if snapshot.screenshot:
        (folder / "screenshot.jpg").write_bytes(snapshot.screenshot)
    details = snapshot.model_dump_json(indent=2, exclude={"html", "screenshot"})
    (folder / "snapshot.json").write_text(details, encoding="utf-8")
    return folder


def save_snapshot(snapshot: PageSnapshot, out: Path) -> Path:
    """Save a site's homepage in its own folder under `out`."""
    return save_page(snapshot, out / site_folder(snapshot.url))


def save_extra_page(snapshot: PageSnapshot, site: Path) -> Path:
    """Save another page read for a site, such as its contact page, in the site's folder."""
    return save_page(snapshot, site / EXTRA_PAGES / site_folder(snapshot.url))


def load_snapshot(folder: Path) -> PageSnapshot:
    """Read back a page that save_page saved."""
    details = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    details.setdefault("loaded_with", "")  # pages saved before this was recorded
    details["html"] = (folder / "page.html").read_text(encoding="utf-8")
    # Read as JSON, so the image copies are decoded from base64 the way they were written.
    snapshot = PageSnapshot.model_validate_json(json.dumps(details))
    screenshot = folder / "screenshot.jpg"
    if not screenshot.exists():
        return snapshot
    return snapshot.model_copy(update={"screenshot": screenshot.read_bytes()})


def saved_folders(directory: Path) -> list[Path]:
    """The folders under a directory that hold a saved site."""
    return sorted(path.parent for path in directory.glob("*/snapshot.json"))


class SavedPages:
    """A Fetcher that gives saved pages instead of loading them, found by the address they
    were saved for. A page that wasn't saved can't be read on a run of saved pages."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    async def fetch(self, url: str) -> PageSnapshot:
        name = site_folder(url)
        found = [self._directory / name, *self._directory.glob(f"*/{EXTRA_PAGES}/{name}")]
        folder = next((place for place in found if (place / "snapshot.json").is_file()), None)
        if folder is None:
            raise FetchError(f"{url} wasn't saved, so this run of saved pages can't read it")
        return await asyncio.to_thread(load_snapshot, folder)
