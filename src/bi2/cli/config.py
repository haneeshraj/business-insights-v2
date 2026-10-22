"""`bi2 config`: choose the LLM with the arrow keys, and see the settings a run uses.

`bi2 config` walks through choosing a provider, then one of its models, then any settings to
change, and saves them in a config file: the user's own, read in every folder and by the MCP
server, or this folder's bi2.toml, for a project, a team or CI. Keys never go in the file: a
missing key can be saved in the system keychain on the way. `bi2 config show` prints the
settings a run would use, and where each one came from.
"""

import asyncio
import json
import re
import sys
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Protocol

import typer
from rich.console import Console
from rich.table import Table

from bi2.adapters.local.keys import save_key
from bi2.cli.doctor import describe, found_keys, hidden
from bi2.core.errors import ModelUnavailable
from bi2.core.providers import JEV, ModelRef, ProviderSettings, parse_model
from bi2.core.settings import (
    CONFIG_FILE,
    Keys,
    Settings,
    config_files,
    user_config_file,
    where_set,
)
from bi2.llm.clients import client_for
from bi2.llm.limits import FreeTier
from bi2.llm.registry import listed_models, model_info

config_app = typer.Typer(
    invoke_without_command=True,
    help="Choose the LLM with the arrow keys, and see the settings a run uses.",
)

_CUSTOM: Final = "+custom"  # the provider option for a server data/providers.toml doesn't list
_LIVE: Final = "+live"  # the model options that ask the provider, or take a typed name
_TYPED: Final = "+typed"
_NONE: Final = "+none"
_MOST_LISTED: Final = 40


class Ui(Protocol):
    """How the walk-through asks: with the arrow keys at a terminal, or scripted in tests."""

    def choose(self, message: str, options: list[tuple[str, str]], default: str | None) -> str:
        """One of the options' values."""
        ...

    def ask(self, message: str, default: str = "") -> str:
        """A typed answer."""
        ...

    def secret(self, message: str) -> str:
        """A typed answer that isn't shown, like a key."""
        ...

    def say(self, text: str) -> None:
        """Tell the user something."""
        ...


class ArrowKeys:
    """The walk-through at a terminal: arrow keys and Enter to choose, typing to answer."""

    def choose(self, message: str, options: list[tuple[str, str]], default: str | None) -> str:
        from prompt_toolkit.shortcuts import choice

        values = {value for value, _ in options}
        return choice(
            message=message,
            options=options,
            default=default if default in values else None,
            bottom_toolbar=" Up and down to move, Enter to choose, Ctrl+C to stop ",
        )

    def ask(self, message: str, default: str = "") -> str:
        from prompt_toolkit import prompt

        return prompt(f"{message} ", default=default).strip()

    def secret(self, message: str) -> str:
        from prompt_toolkit import prompt

        return prompt(f"{message} ", is_password=True).strip()

    def say(self, text: str) -> None:
        Console().print(text, markup=False, highlight=False)


def _key_note(name: str, provider: ProviderSettings, keys: Keys, found: dict[str, str]) -> str:
    if keys.get(name) is not None:
        return f"key found, in the {found.get(name, 'environment')}"
    return "no key needed" if not provider.needs_key else "no key yet"


class Walkthrough:
    """Choosing the LLM: a provider, then a model, then any settings, then where to save."""

    def __init__(self, ui: Ui, settings: Settings | None = None) -> None:
        self.ui = ui
        self.settings = settings or Settings()
        self.known = self.settings.all_providers()
        self.keys, self.found = found_keys(self.settings)
        self.ai: dict[str, Any] = {}  # the [ai] settings chosen
        self.thresholds: dict[str, Any] = {}
        self.providers: dict[str, dict[str, Any]] = {}  # providers added or changed

    def provider(self, message: str, current: str | None) -> str:
        """A provider, by its name."""
        options = [
            (
                name,
                f"{provider.title or name}  ·  {_key_note(name, provider, self.keys, self.found)}",
            )
            for name, provider in self.known.items()
        ]
        options.append((_CUSTOM, "Another OpenAI-compatible server  ·  give its address"))
        name = self.ui.choose(message, options, current)
        return self._custom() if name == _CUSTOM else name

    def _custom(self) -> str:
        name = ""
        while not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
            name = self.ui.ask("A short name for it, like myserver:").lower()
        base_url = self.ui.ask("Its address, ending in /v1:", "http://localhost:8000/v1")
        variable = self.ui.ask("The environment variable its key is in (empty for none):")
        table: dict[str, Any] = {"title": name, "base_url": base_url, "needs_key": bool(variable)}
        if variable:
            table["keys"] = [variable]
        self.providers[name] = table
        self.known = self.settings.all_providers() | {name: ProviderSettings(**table)}
        return name

    def _server(self, name: str) -> None:
        """For a server on the user's own machine, its address, which may not be the usual one."""
        provider = self.known[name]
        if not provider.local:
            return
        address = self.ui.ask(f"{provider.title or name}'s address:", provider.base_url)
        if address and address != provider.base_url:
            self.providers[name] = {**self.providers.get(name, {}), "base_url": address}
            self.known = self.known | {name: provider.model_copy(update={"base_url": address})}

    def _listed(self, name: str) -> list[str]:
        """The models the provider lists for the user's key, or none when it can't be asked."""
        provider = self.known[name]
        key = self.keys.get(name)
        if key is None and provider.needs_key:
            self.ui.say(f"Listing {provider.title or name}'s models needs its key first.")
            return []
        probe = ModelRef(name, provider.models[0] if provider.models else "any")
        client = client_for(
            probe,
            provider=provider,
            key=key.get_secret_value() if key else None,
            settings=self.settings,
            limits=FreeTier(),
        )

        async def ask() -> list[str]:
            async with client:
                return await client.models()

        try:
            return asyncio.run(ask())
        except ModelUnavailable as exc:
            self.ui.say(f"Couldn't list the models: {exc}")
            return []

    def model(self, name: str, current: str | None) -> str:
        """One of the provider's models, by its own name."""
        provider = self.known[name]
        while True:
            options: list[tuple[str, str]] = []
            for info in listed_models(name):
                options.append(
                    (
                        info.model,
                        f"{info.model}  ·  {describe(model_info(info.ref, self.settings.models))}",
                    )
                )
            for model in provider.models:
                if model not in {value for value, _ in options}:
                    options.append((model, f"{model}  ·  price not listed"))
            if current and current not in {value for value, _ in options}:
                options.insert(0, (current, f"{current}  ·  the one set now"))
            options.append(
                (_LIVE, f"The models your key can use, as {provider.title or name} lists them")
            )
            options.append((_TYPED, "Type a model's name"))
            choice = self.ui.choose(f"Which {provider.title or name} model?", options, current)
            if choice == _TYPED:
                if typed := self.ui.ask("The model's name, as the provider writes it:"):
                    return typed
                continue
            if choice != _LIVE:
                return choice
            listed = self._listed(name)
            if listed:
                shown = [(model, model) for model in listed[:_MOST_LISTED]]
                if len(listed) > _MOST_LISTED:
                    self.ui.say(
                        f"{len(listed)} models: the first {_MOST_LISTED} are shown; type a name for the others."
                    )
                shown.append((_TYPED, "Type a model's name"))
                picked = self.ui.choose("Which one?", shown, current)
                if picked != _TYPED:
                    return picked
                if typed := self.ui.ask("The model's name, as the provider writes it:"):
                    return typed

    def key(self, name: str) -> None:
        """Offer to save a provider's missing key in the system keychain."""
        provider = self.known.get(name)
        if self.keys.get(name) is not None or (provider is not None and not provider.needs_key):
            return
        variables = " or ".join(provider.keys) if provider else "JEV_API_KEY"
        title = provider.title if provider else "Jev"
        answer = self.ui.choose(
            f"There's no {title} key yet. Save one now?",
            [
                ("save", "Type it now, to keep in the system keychain (it isn't shown)"),
                ("later", f"Later: set {variables}, or run `bi2 keys set {name}`"),
            ],
            "save",
        )
        if answer != "save":
            return
        typed = self.ui.secret(f"{title} key:")
        if not typed:
            return
        try:
            save_key(name, typed)
        except Exception as exc:  # noqa: BLE001  # keyring raises its own errors per backend
            self.ui.say(f"No keychain to save it in ({exc}); set {variables} instead.")
            return
        from pydantic import SecretStr

        self.keys = self.keys.with_key(name, SecretStr(typed))
        self.found[name] = "keychain"
        self.ui.say(f"Saved the {name} key ({hidden(typed)}) in the system keychain.")

    def _value(self, name: str) -> Any:
        return self.ai.get(name, getattr(self.settings.ai, name))

    def _menu(self) -> list[tuple[str, str]]:
        jev_note = "" if self.keys.jev else ", but there's no Jev key"
        search = self._value("search_model") or "the LLM itself"
        accept = self.thresholds.get("accept", self.settings.thresholds.accept)
        return [
            ("done", "Done: save these settings"),
            ("backup_model", f"Backup model: {self._value('backup_model') or 'none'}"),
            ("temperature", f"Temperature: {self._value('temperature')}"),
            ("timeout_s", f"Seconds a model call may take: {self._value('timeout_s')}"),
            ("jev", f"Jev makes the typed choices: {'yes' if self._value('jev') else 'no'}{jev_note}"),
            ("search", f"Web search for head offices no page gives: {'on' if self._value('search') else 'off'}, by {search}"),
            ("calls_per_site", f"Model calls a site, at most: {self._value('calls_per_site')}"),
            ("accept", f"Confidence needed to accept an answer: {accept}"),
        ]  # fmt: skip

    def _number(self, message: str, current: Any, low: float, high: float) -> float | None:
        typed = self.ui.ask(f"{message} ({low} to {high}):", str(current))
        try:
            value = float(typed)
        except ValueError:
            self.ui.say("That isn't a number; nothing changed.")
            return None
        if not low <= value <= high:
            self.ui.say(f"It has to be from {low} to {high}; nothing changed.")
            return None
        return value

    def settings_menu(self) -> None:
        """Change any of the settings, or keep them all as they are."""
        while (picked := self.ui.choose("Any settings to change?", self._menu(), "done")) != "done":
            if picked == "backup_model":
                current = self._value("backup_model")
                choice = self.ui.choose(
                    "A backup model, asked when the first one can't answer?",
                    [("pick", "Choose one"), (_NONE, "No backup")],
                    "pick",
                )
                if choice == _NONE:
                    self.ai["backup_model"] = ""
                    continue
                ref = parse_model(current, self.known) if current else None
                name = self.provider("The backup model's provider?", ref.provider if ref else None)
                model = self.model(name, ref.model if ref and ref.provider == name else None)
                self._server(name)
                self.key(name)
                self.ai["backup_model"] = f"{name}:{model}"
            elif picked == "temperature":
                if (value := self._number("Temperature: 0 gives the same answer every time", self._value("temperature"), 0, 2)) is not None:  # fmt: skip
                    self.ai["temperature"] = value
            elif picked == "timeout_s":
                if (value := self._number("Seconds a call may take", self._value("timeout_s"), 5, 600)) is not None:  # fmt: skip
                    self.ai["timeout_s"] = value
            elif picked == "calls_per_site":
                if (value := self._number("Model calls a site, at most", self._value("calls_per_site"), 0, 100)) is not None:  # fmt: skip
                    self.ai["calls_per_site"] = int(value)
            elif picked == "accept":
                current = self.thresholds.get("accept", self.settings.thresholds.accept)
                if (value := self._number("Confidence needed to accept an answer", current, 0.5, 1)) is not None:  # fmt: skip
                    self.thresholds["accept"] = value
            elif picked == "jev":
                on = self.ui.choose(
                    "Should Jev make the typed choices, like which box is the logo?",
                    [("yes", "Yes: Jev is cheaper for choices, and can't make an answer up"),
                     ("no", "No: the LLM makes them too")],
                    "yes" if self._value("jev") else "no",
                ) == "yes"  # fmt: skip
                self.ai["jev"] = on
                if on:
                    self.key(JEV)
            elif picked == "search":
                self._search()

    def _search(self) -> None:
        choice = self.ui.choose(
            "Search the web for head offices no page gives?",
            [("llm", "Yes, with the LLM (only Gemini can search here)"),
             ("gemini", "Yes, with a Gemini model, whatever the LLM is"),
             ("off", "No")],
            "llm" if self._value("search") and not self._value("search_model") else "gemini",
        )  # fmt: skip
        self.ai["search"] = choice != "off"
        if choice == "llm":
            self.ai["search_model"] = ""
        elif choice == "gemini":
            model = self.model("gemini", None)
            self.ai["search_model"] = f"gemini:{model}"
            self.key("gemini")

    def where(self) -> Path:
        """The file to save in."""
        here = Path.cwd() / CONFIG_FILE
        choice = self.ui.choose(
            "Where should these settings go?",
            [
                (
                    "user",
                    f"Your settings, for every folder and the MCP server: {user_config_file()}",
                ),
                ("project", f"This folder only, for a project, a team or CI: {here}"),
            ],
            "user",
        )
        return user_config_file() if choice == "user" else here

    def run(self) -> Path:
        """The whole walk-through. Returns the file the settings were saved in."""
        current = parse_model(self.settings.ai.llm_model, self.known)
        name = self.provider(
            "Which provider should answer what the rules aren't sure of?", current.provider
        )
        model = self.model(name, current.model if current.provider == name else None)
        self._server(name)
        self.key(name)
        self.ai["llm_model"] = f"{name}:{model}"
        self.ai["llm"] = True
        self.settings_menu()
        path = self.where()
        save(path, self.changes())
        self.ui.say(
            f"Saved in {path}. `bi2 config show` shows every setting; `bi2 doctor` checks the keys."
        )
        return path

    def changes(self) -> dict[str, Any]:
        """What to write: only the settings chosen."""
        found: dict[str, Any] = {"ai": self.ai}
        if self.thresholds:
            found["thresholds"] = self.thresholds
        if self.providers:
            found["providers"] = self.providers
        return found


def _merge(into: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            _merge(into[key], value)
        else:
            into[key] = value
    return into


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | Decimal):
        return str(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return json.dumps(str(value))


def to_toml(data: dict[str, Any]) -> str:
    """Settings as TOML: plain values first, then each table."""
    lines = [
        "# bi2's settings. `bi2 config` writes this file; it can be edited by hand too.",
        "# Keys never go here: they're in environment variables or the system keychain.",
    ]
    lines += [
        f"{_toml_key(k)} = {_toml_value(v)}" for k, v in data.items() if not isinstance(v, dict)
    ]

    def table(path: list[str], values: dict[str, Any]) -> None:
        plain = {k: v for k, v in values.items() if not isinstance(v, dict)}
        if plain:
            lines.extend(["", f"[{'.'.join(_toml_key(part) for part in path)}]"])
            lines.extend(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in plain.items())
        for k, v in values.items():
            if isinstance(v, dict):
                table([*path, k], v)

    for key, value in data.items():
        if isinstance(value, dict):
            table([key], value)
    return "\n".join(lines) + "\n"


def save(path: Path, changes: dict[str, Any]) -> None:
    """Write the chosen settings into a config file, keeping what else it holds."""
    data: dict[str, Any] = {}
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))  # with a byte order mark too
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_toml(_merge(data, changes)), encoding="utf-8")


@config_app.callback()
def config(context: typer.Context) -> None:
    """Choose a provider, a model and its settings with the arrow keys, and save them."""
    if context.invoked_subcommand is not None:
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        typer.echo(
            "`bi2 config` needs a terminal to choose in. Elsewhere, set the model in bi2.toml "
            '(ai.llm_model = "openai:gpt-5.4-mini") or as BI2_AI__LLM_MODEL; '
            "`bi2 config show` prints every setting."
        )
        raise typer.Exit(code=2)
    try:
        Walkthrough(ArrowKeys()).run()
    except (KeyboardInterrupt, EOFError):
        typer.echo("Stopped: nothing was saved.")
        raise typer.Exit(code=1) from None


@config_app.command("show")
def show() -> None:
    """Print the settings a run here would use, and where each one came from."""
    settings = Settings()
    console = Console()
    for path in config_files():
        console.print(f"{path}: {'read' if path.is_file() else 'none'}", markup=False)
    table = Table(title="Settings")
    table.add_column("Setting")
    table.add_column("Value")
    table.add_column("From")
    for name, value, source in where_set(settings):
        table.add_row(name, value, source)
    console.print(table)
    keys, found = found_keys(settings)
    held = [f"{name} ({where})" for name, where in found.items() if keys.get(name) is not None]
    console.print("Keys found: " + (", ".join(held) or "none"), markup=False)
    if settings.providers:
        console.print("Providers added or changed: " + ", ".join(settings.providers), markup=False)
