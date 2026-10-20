"""`bi2 doctor` and `bi2 keys`: check that v2 can run, and keep keys in the keychain."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.table import Table

from bi2 import USER_AGENT
from bi2.adapters.local.keys import PROVIDERS, Provider, delete_key, save_key, with_keychain
from bi2.core.settings import Settings, keys_from_environment
from bi2.llm.registry import model_info

keys_app = typer.Typer(no_args_is_help=True, help="Keep API keys in the system keychain.")


def _hidden(key: str) -> str:
    return f"...{key[-4:]}" if len(key) > 8 else "set"


async def _check(url: str, headers: dict[str, str]) -> str:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return f"can't be reached: {type(exc).__name__}"
    return "ok" if response.status_code == 200 else f"answered {response.status_code}"


async def _checks(gemini: str | None, jev: str | None) -> dict[str, str]:
    agent = {"User-Agent": USER_AGENT}
    checks = {
        "Wikidata": _check("https://www.wikidata.org/w/api.php?action=query&format=json", agent),
        "Nominatim (OpenStreetMap)": _check("https://nominatim.openstreetmap.org/status?format=json", agent),
    }  # fmt: skip
    if gemini:
        url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"
        checks["Gemini"] = _check(url, {"x-goog-api-key": gemini})
    if jev:
        checks["Jev"] = _check(
            "https://api.typesafe.ai/v1/models", {"Authorization": f"Bearer {jev}"}
        )
    results = await asyncio.gather(*checks.values())
    return dict(zip(checks, results, strict=True))


def _browser() -> str:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            playwright.chromium.launch(headless=True).close()
    except Exception as exc:  # noqa: BLE001  # any failure to start means the browser isn't usable
        return f"not usable: {str(exc).splitlines()[0][:80]}; run `playwright install chromium`"
    return "ok"


def doctor() -> None:
    """Check the keys, the models, the browser and the free services v2 uses."""
    console = Console()
    settings = Settings()
    keys, found = with_keychain(keys_from_environment())
    table = Table(title="bi2 doctor")
    table.add_column("Check")
    table.add_column("Result")
    for provider in PROVIDERS:
        key = getattr(keys, provider)
        shown = (
            f"{_hidden(key.get_secret_value())}, from the {found[provider]}" if key else "not set"
        )
        table.add_row(f"{provider.title()} key", shown)
    gemini = keys.gemini.get_secret_value() if keys.gemini else None
    jev = keys.jev.get_secret_value() if keys.jev else None
    for name, result in asyncio.run(_checks(gemini, jev)).items():
        table.add_row(name, result)
    for model in (settings.ai.jev_model, settings.ai.llm_model, settings.ai.backup_model):
        try:
            info = model_info(model)
            table.add_row(
                f"Model {model}", f"{info.per_minute}/min, {info.per_day}/day on the free tier"
            )
        except KeyError:
            table.add_row(f"Model {model}", "not in data/models.toml")
    usage = Path(typer.get_app_dir("bi2")) / "free-tier-usage.json"
    if usage.is_file():
        counts = json.loads(usage.read_text(encoding="utf-8"))
        today = ", ".join(f"{m} {n}" for m, n in counts.get("requests", {}).items()) or "none"
        table.add_row("Requests today", today)
    table.add_row("Browser (Playwright Chromium)", _browser())
    console.print(table)
    if not keys.gemini and not keys.jev:
        console.print(
            "No model keys: answers come from the rules alone. Set JEV_API_KEY or GEMINI_API_KEY, or run `bi2 keys set jev`."
        )


@keys_app.command("set")
def set_key(provider: Annotated[Provider, typer.Argument(help="gemini or jev")]) -> None:
    """Save a provider's key in the system keychain. The key is typed, not shown."""
    key = typer.prompt(f"{provider.title()} API key", hide_input=True).strip()
    try:
        save_key(provider, key)
    except Exception as exc:  # keyring raises its own errors per backend
        typer.echo(
            f"error: no keychain to save it in ({exc}); set it as an environment variable instead",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    typer.echo(f"Saved the {provider} key ({_hidden(key)}) in the system keychain.")


@keys_app.command("show")
def show_keys() -> None:
    """Show which keys are set and where, with all but their last four characters hidden."""
    keys, found = with_keychain(keys_from_environment())
    for provider in PROVIDERS:
        key = getattr(keys, provider)
        where = (
            f"{_hidden(key.get_secret_value())}, from the {found[provider]}" if key else "not set"
        )
        typer.echo(f"{provider}: {where}")


@keys_app.command("delete")
def delete(provider: Annotated[Provider, typer.Argument(help="gemini or jev")]) -> None:
    """Remove a provider's key from the system keychain."""
    typer.echo(
        f"Removed the {provider} key." if delete_key(provider) else f"No {provider} key was saved."
    )
