"""Stand-ins for the ports, so logic can be tested without a browser, the network or a disk."""

from bi2.core.context import RunContext
from bi2.core.errors import FetchError
from bi2.core.models import PageSnapshot
from bi2.core.settings import Settings, Thresholds


class FakeFetcher:
    """Serves pages from a dictionary of URL to snapshot."""

    def __init__(self, pages: dict[str, PageSnapshot] | None = None) -> None:
        self.pages = pages or {}

    async def fetch(self, url: str) -> PageSnapshot:
        if url not in self.pages:
            raise FetchError(f"couldn't load {url}")
        return self.pages[url]


class FakeDownloader:
    """Serves files from a dictionary of URL to content, and remembers what was asked for."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = files or {}
        self.asked: list[str] = []

    async def download(self, url: str, *, max_bytes: int) -> bytes:
        self.asked.append(url)
        if url not in self.files:
            raise FetchError(f"couldn't download {url}")
        if len(self.files[url]) > max_bytes:
            raise FetchError(f"{url} is larger than {max_bytes} bytes")
        return self.files[url]


class MemoryFiles:
    """Keeps a run's files in memory."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def save(self, path: str, data: bytes) -> str:
        self.files[path] = data
        return path

    async def read(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]


def fake_context(
    *,
    pages: dict[str, PageSnapshot] | None = None,
    downloads: dict[str, bytes] | None = None,
    files: MemoryFiles | None = None,
    accept: float = 0.85,
) -> RunContext:
    """A RunContext built from the stand-ins above."""
    return RunContext(
        settings=Settings(thresholds=Thresholds(accept=accept)),
        fetcher=FakeFetcher(pages),
        downloader=FakeDownloader(downloads),
        files=files or MemoryFiles(),
    )
