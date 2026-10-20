"""Interfaces for everything that does I/O. Logic depends on these; infrastructure implements
them; entry points choose which implementation to use."""

from typing import Protocol

from bi2.core.asking import Ask, Decision, Generated, Prompt
from bi2.core.models import KnownBusiness, PageSnapshot


class Fetcher(Protocol):
    """Loads a page and captures what's needed to build its evidence."""

    async def fetch(self, url: str) -> PageSnapshot:
        """Load one page. Raises UnsafeUrl, PageTimeout or FetchError."""
        ...


class Downloader(Protocol):
    """Downloads a file, such as a logo, with the same safety checks as loading pages."""

    async def download(self, url: str, *, max_bytes: int, referer: str | None = None) -> bytes:
        """The file's content. Raises UnsafeUrl, or FetchError, including when the file is
        larger than max_bytes. The referer is the page the file is on, which some image hosts
        ask for."""
        ...


class FileStore(Protocol):
    """The files a run produces, such as screenshots and logos, at paths relative to the
    run's output folder, like "example-cafe.ca/logo.png"."""

    async def save(self, path: str, data: bytes) -> str:
        """Save a file, replacing one already there, and return its path."""
        ...

    async def read(self, path: str) -> bytes:
        """Read a file saved earlier."""
        ...


class KnowledgeBase(Protocol):
    """A public knowledge base, like Wikidata, that knows big businesses by their websites."""

    async def business_with_website(self, url: str) -> KnownBusiness | None:
        """The business whose official website this is, or None when the knowledge base has
        none. Raises LookupUnavailable when it can't be reached."""
        ...


class KnowsNothing:
    """The knowledge base for runs and tests that use none."""

    async def business_with_website(self, url: str) -> KnownBusiness | None:
        return None


class Decider(Protocol):
    """Answers typed questions about evidence: pick one, yes or no, rate, or find in an image.
    Jev, or an LLM standing in for it."""

    @property
    def name(self) -> str:
        """Who answers, like "jev" or "gemini", for the audit trail."""
        ...

    async def decide(self, ask: Ask) -> Decision:
        """Answer every question in the Ask. Raises ModelUnavailable when the model can't
        answer: its provider failed, or its free-tier budget is used up."""
        ...


class LanguageModel(Protocol):
    """An LLM that answers a Prompt with JSON of the shape it asks for."""

    @property
    def name(self) -> str:
        """Who answers, like "gemini", for the audit trail."""
        ...

    async def generate(self, prompt: Prompt) -> Generated:
        """Answer the prompt. Raises ModelUnavailable when the model can't answer."""
        ...
