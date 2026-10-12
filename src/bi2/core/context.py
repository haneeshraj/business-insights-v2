"""RunContext: the settings and ports a run needs, handed to the pipeline and the resolvers."""

from dataclasses import dataclass, field

from bi2.core.ports import Downloader, Fetcher, FileStore
from bi2.core.routing import Routing
from bi2.core.settings import Settings


@dataclass(frozen=True)
class RunContext:
    """Everything a run needs from the outside world. Entry points build it from real
    implementations (bi2/wiring.py), and tests build it from fakes. More ports join as the
    fields that need them are built: models, search, geocoding."""

    settings: Settings
    fetcher: Fetcher
    downloader: Downloader
    files: FileStore
    routing: Routing = field(default_factory=Routing)  # which answers to keep without AI
