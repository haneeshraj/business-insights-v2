"""Pages saved by `bi2 dev fetch`: writing them, and reading them back so later steps can be
tried on them without loading the sites again."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from bi2.core.models import PageSnapshot


def folder_name(url: str) -> str:
    """A folder name for a page, such as `example-cafe.ca_menu`."""
    parts = urlsplit(url)
    name = (parts.netloc.removeprefix("www.") + parts.path).strip("/")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name) or "page"


def save_snapshot(snapshot: PageSnapshot, out: Path) -> Path:
    """Save the screenshot, the HTML and everything else the browser captured."""
    folder = out / folder_name(snapshot.url)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "page.html").write_text(snapshot.html, encoding="utf-8")
    if snapshot.screenshot:
        (folder / "screenshot.jpg").write_bytes(snapshot.screenshot)
    details = snapshot.model_dump_json(indent=2, exclude={"html", "screenshot"})
    (folder / "snapshot.json").write_text(details, encoding="utf-8")
    return folder


def load_snapshot(folder: Path) -> PageSnapshot:
    """Read back a page that save_snapshot saved."""
    details = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    details.setdefault("loaded_with", "")  # pages saved before this was recorded
    screenshot = folder / "screenshot.jpg"
    return PageSnapshot.model_validate(
        {
            **details,
            "html": (folder / "page.html").read_text(encoding="utf-8"),
            "screenshot": screenshot.read_bytes() if screenshot.exists() else None,
        }
    )


def saved_folders(directory: Path) -> list[Path]:
    """The folders under a directory that hold a saved page."""
    return sorted(path.parent for path in directory.glob("*/snapshot.json"))
