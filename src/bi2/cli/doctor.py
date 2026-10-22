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
from bi2.adapters.local.keys import delete_key, provider_names, save_key, with_keychain
from bi2.core.errors import ModelUnavailable
from bi2.core.providers import JEV, ModelRef, ProviderSettings, parse_model
from bi2.core.settings import Keys, Settings, config_files, keys_from_environment
from bi2.llm.clients import client_for
from bi2.llm.limits import FreeTier
from bi2.llm.registry import ModelInfo, model_info

keys_app = typer.Typer(no_args_is_help=True, help="Keep API keys in the system keychain.")


def hidden(key: str) -> str:
    """A key with all but its last four characters hidden."""
    return f"...{key[-4:]}" if len(key) > 8 else "set"


def found_keys(settings: Settings | None = None) -> tuple[Keys, dict[str, str]]:
    """Every key the environment and the keychain hold, and where each was found."""
    known = (settings or Settings()).all_providers()
    return with_keychain(keys_from_environment(known), known)


async def _check(url: str, headers: dict[str, str]) -> str:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return f"can't be reached: {type(exc).__name__}"
    return "ok" if response.status_code == 200 else f"answered {response.status_code}"


async def check_model(
    ref: ModelRef, provider: ProviderSettings, key: str | None, settings: Settings
) -> str:
    """Whether the model's provider takes the key, and lists the model for it."""
    client = client_for(ref, provider=provider, key=key, settings=settings, limits=FreeTier())
    try:
        async with client:
            listed = await client.models()
    except ModelUnavailable as exc:
        return str(exc)[:120]
    if ref.model in listed or not listed:
        return "ok"
    return f"the key works, but {provider.title or ref.provider} doesn't list {ref.model} for it"


async def _checks(
    settings: Settings, keys: Keys, models: list[tuple[str, ModelRef]]
) -> dict[str, str]:
    agent = {"User-Agent": USER_AGENT}
    checks = {
        "Wikidata": _check("https://www.wikidata.org/w/api.php?action=query&format=json", agent),
        "Nominatim (OpenStreetMap)": _check("https://nominatim.openstreetmap.org/status?format=json", agent),
    }  # fmt: skip
    if keys.jev:
        checks["Jev"] = _check(
            "https://api.typesafe.ai/v1/models",
            {"Authorization": f"Bearer {keys.jev.get_secret_value()}"},
        )
    known = settings.all_providers()
    for role, ref in models:
        if ref.provider == JEV or role == "Decider":
            continue
        provider = known[ref.provider]
        key = keys.get(ref.provider)
        if key is None and provider.needs_key:
            continue
        secret = key.get_secret_value() if key else None
        checks[f"{role}: {ref}"] = check_model(ref, provider, secret, settings)
    results = await asyncio.gather(*checks.values())
    return dict(zip(checks, results, strict=True))


_ROLES = {"llm_model": "LLM", "backup_model": "Backup", "search_model": "Search"}


def configured_models(settings: Settings) -> list[tuple[str, ModelRef]]:
    """The models a run would use, by their part in it. Raises ValueError for a model whose
    provider can't be told."""
    named = [(_ROLES[setting], ref) for setting, ref in settings.llm_models().items()]
    decider = settings.ai.jev_model
    return (
        [*named, ("Decider", parse_model(decider, settings.all_providers()))] if decider else named
    )


def check_models(settings: Settings) -> None:
    """Stop the command, saying what's wrong, when the LLMs a run would ask can't be told
    apart, rather than in the middle of the run."""
    if not (settings.ai.enabled and settings.ai.llm):
        return
    try:
        settings.llm_models()
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from None


def describe(info: ModelInfo) -> str:
    """A model's price and limits, in a few words."""
    if info.listed:
        price = f"${info.input_per_million} / ${info.output_per_million} per million tokens"
    else:
        price = "price not listed: its calls count as free in the logs"
    return f"{price}; {info.per_minute} a minute, {info.per_day} a day"


def _browser() -> str:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            playwright.chromium.launch(headless=True).close()
    except Exception as exc:  # noqa: BLE001  # any failure to start means the browser isn't usable
        return f"not usable: {str(exc).splitlines()[0][:80]}; run `playwright install chromium`"
    return "ok"


def doctor() -> None:
    """Check the config, the keys, the models, the browser and the free services v2 uses."""
    console = Console()
    settings = Settings()
    keys, found = found_keys(settings)
    known = settings.all_providers()
    table = Table(title="bi2 doctor")
    table.add_column("Check")
    table.add_column("Result")
    for path in config_files():
        table.add_row("Config file", f"{path} ({'read' if path.is_file() else 'none'})")
    try:
        models = configured_models(settings)
    except ValueError as exc:
        models = []
        table.add_row("Models", f"can't be used: {exc}")
    needed = {ref.provider for _, ref in models}
    for name in provider_names(known):
        key = keys.get(name)
        if key is None and name not in needed:
            continue
        title = "Jev" if name == JEV else known[name].title or name
        if key is not None:
            shown = f"{hidden(key.get_secret_value())}, from the {found[name]}"
        elif name != JEV and not known[name].needs_key:
            shown = "none needed"
        else:
            variables = " or ".join(known[name].keys) if name != JEV else "JEV_API_KEY"
            shown = f"not set: set {variables}, or run `bi2 keys set {name}`"
        table.add_row(f"{title} key", shown)
    for role, ref in models:
        table.add_row(f"{role} model", f"{ref}: {describe(model_info(ref, settings.models))}")
    for name, result in asyncio.run(_checks(settings, keys, models)).items():
        table.add_row(name, result)
    usage = Path(typer.get_app_dir("bi2")) / "free-tier-usage.json"
    if usage.is_file():
        counts = json.loads(usage.read_text(encoding="utf-8"))
        today = ", ".join(f"{m} {n}" for m, n in counts.get("requests", {}).items()) or "none"
        table.add_row("Requests today", today)
    table.add_row("Browser (Playwright Chromium)", _browser())
    console.print(table)
    if not keys.llm and keys.jev is None:
        console.print(
            "No model keys: answers come from the rules alone. Run `bi2 config` to choose a "
            "provider and a model, or `bi2 keys set <provider>`."
        )


def _provider(name: str) -> str:
    known = provider_names(Settings().all_providers())
    if name not in known:
        typer.echo(f"error: no provider named {name}. The providers: {', '.join(known)}", err=True)
        raise typer.Exit(code=2)
    return name


@keys_app.command("set")
def set_key(
    provider: Annotated[str, typer.Argument(help="The provider, like jev, gemini or openai.")],
) -> None:
    """Save a provider's key in the system keychain. The key is typed, not shown."""
    provider = _provider(provider)
    key = typer.prompt(f"{provider} API key", hide_input=True).strip()
    try:
        save_key(provider, key)
    except Exception as exc:  # keyring raises its own errors per backend
        typer.echo(
            f"error: no keychain to save it in ({exc}); set it as an environment variable instead",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    typer.echo(f"Saved the {provider} key ({hidden(key)}) in the system keychain.")


@keys_app.command("show")
def show_keys() -> None:
    """Show which keys are set and where, with all but their last four characters hidden."""
    settings = Settings()
    keys, found = found_keys(settings)
    for provider, where in found.items():
        key = keys.get(provider)
        if key is not None:
            typer.echo(f"{provider}: {hidden(key.get_secret_value())}, from the {where}")
    known = settings.all_providers()
    missing: dict[str, str] = {}
    try:
        models = configured_models(settings)
    except ValueError as exc:
        models = []
        typer.echo(f"error: {exc}", err=True)
    for role, ref in models:
        needs = ref.provider == JEV or known[ref.provider].needs_key
        if needs and keys.get(ref.provider) is None:
            missing.setdefault(ref.provider, f"the {role.lower()} model, {ref}, needs it")
    for provider, why in missing.items():
        typer.echo(f"{provider}: not set ({why})")
    if not found and not missing:
        typer.echo("No keys are set. Run `bi2 config`, or `bi2 keys set <provider>`.")


@keys_app.command("delete")
def delete(
    provider: Annotated[str, typer.Argument(help="The provider, like jev, gemini or openai.")],
) -> None:
    """Remove a provider's key from the system keychain."""
    provider = _provider(provider)
    typer.echo(
        f"Removed the {provider} key." if delete_key(provider) else f"No {provider} key was saved."
    )
