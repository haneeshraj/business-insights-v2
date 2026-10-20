"""RunContext: the settings and ports a run needs, handed to the pipeline and the resolvers."""

from dataclasses import dataclass, field

from bi2.core.ports import (
    Decider,
    Downloader,
    Fetcher,
    FileStore,
    KnowledgeBase,
    KnowsNothing,
    LanguageModel,
)
from bi2.core.settings import Settings


@dataclass(frozen=True)
class RunContext:
    """Everything a run needs from the outside world. Entry points build it from real
    implementations (bi2/wiring.py), and tests build it from fakes. More ports join as the
    fields that need them are built: search and geocoding."""

    settings: Settings
    fetcher: Fetcher
    downloader: Downloader
    files: FileStore
    # Facts about big businesses by their websites, for pages that block us.
    knowledge: KnowledgeBase = field(default_factory=KnowsNothing)
    # Models, for the answers the rules aren't sure of. None when there's no key for one, or
    # model calls are turned off; the steps that need them then pass.
    decider: Decider | None = None  # Jev, or an LLM standing in for it
    llm: LanguageModel | None = None  # for generations, and the Decider's backup
    second: Decider | None = None  # another model, for a second opinion when the first is unsure
