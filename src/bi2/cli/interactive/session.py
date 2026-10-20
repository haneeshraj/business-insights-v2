"""The interactive session's loop: read a line, analyze the addresses in it or run its command,
show the outcome. One browser and one set of model clients stay open for the whole session."""

import asyncio
from pathlib import Path

from rich.console import Console

from bi2.adapters.local.answers import CallLog
from bi2.cli.analyze import app_folder
from bi2.cli.interactive.commands import COMMANDS, HELP, Results
from bi2.core.context import RunContext
from bi2.core.models import SiteResult, Status
from bi2.pipeline import analyze_url
from bi2.wiring import local_context

_SHORT = {
    Status.OK: "ok",
    Status.NEEDS_REVIEW: "review",
    Status.NOT_FOUND: "none",
    Status.ERROR: "error",
}
_AT_ONCE = 3


def _line(result: SiteResult) -> str:
    if result.error:
        return f"  {result.page.url}  failed: {result.error}"
    fields = "  ".join(
        f"{name.split('_')[0]} {_SHORT[f.status]}" for name, f in result.field_results.items()
    )
    return f"  {result.page.url}  {fields}  {result.seconds:.1f} s"


async def _analyze(urls: list[str], ctx: RunContext, results: Results, console: Console) -> None:
    limit = asyncio.Semaphore(_AT_ONCE)

    async def one(url: str) -> SiteResult:
        async with limit:
            result, _ = await analyze_url(url, ctx)
            return result

    for task in asyncio.as_completed([one(url) for url in urls]):
        result = await task
        results[result.page.url] = result
        console.print(_line(result), markup=False, highlight=False)


async def run_session(console: Console, *, out: Path = Path("bi2-results/session")) -> None:
    """Read commands and addresses until /quit, Ctrl+D or a second Ctrl+C."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory

    folder = app_folder()
    folder.mkdir(parents=True, exist_ok=True)
    prompt: PromptSession[str] = PromptSession(history=FileHistory(str(folder / "history")))
    log = CallLog(out / "model-calls.jsonl")
    results: Results = {}
    console.print("Business Insights v2. Paste website addresses, or type /help.", markup=False)
    async with local_context(
        out,
        kept_answers=folder / "answers",
        usage_file=folder / "free-tier-usage.json",
        call_log=log,
    ) as ctx:
        while True:
            try:
                line = (await prompt.prompt_async("> ")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            words = line.split()
            if words[0] == "/quit":
                break
            if words[0].startswith("/"):
                handler = COMMANDS.get(words[0])
                console.print(handler(results, words[1:]) if handler else HELP)
                continue
            urls = [w if "://" in w else f"https://{w}" for w in words]
            try:
                await _analyze(urls, ctx, results, console)
            except KeyboardInterrupt:
                console.print("Stopped.", markup=False)
            spent = log.spent
            console.print(
                f"  {log.calls} model calls so far, ${spent.usd:.4f} at list price", markup=False
            )
