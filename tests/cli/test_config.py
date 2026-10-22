"""Tests for `bi2 config`: choosing the LLM step by step, and saving and showing the settings."""

import tomllib
from collections import deque
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from bi2.cli import config as config_cli
from bi2.cli.analyze import run_settings
from bi2.cli.config import Walkthrough, save, to_toml
from bi2.cli.main import app
from bi2.core.settings import Keys

runner = CliRunner()


class _Scripted:
    """Answers the walk-through's questions in order, and keeps what it was shown."""

    def __init__(
        self, choices: list[str], answers: tuple[str, ...] | list[str] = (),
        secrets: tuple[str, ...] | list[str] = (),
    ) -> None:  # fmt: skip
        self.choices, self.answers, self.secrets = deque(choices), deque(answers), deque(secrets)
        self.shown: list[tuple[str, list[tuple[str, str]]]] = []
        self.said: list[str] = []

    def choose(self, message: str, options: list[tuple[str, str]], default: str | None) -> str:
        self.shown.append((message, options))
        picked = self.choices.popleft()
        assert picked in {value for value, _ in options}, (message, picked, options)
        return picked

    def ask(self, message: str, default: str = "") -> str:
        return self.answers.popleft() if self.answers else default

    def secret(self, message: str) -> str:
        return self.secrets.popleft()

    def say(self, text: str) -> None:
        self.said.append(text)


@pytest.fixture
def here(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A folder to save in, no keys, and a keychain that keeps what's saved in a dict."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_cli, "found_keys", lambda settings=None: (Keys(), {}))
    monkeypatch.setattr(config_cli, "user_config_file", lambda: tmp_path / "user" / "bi2.toml")
    saved: dict[str, str] = {}
    monkeypatch.setattr(
        config_cli, "save_key", lambda provider, key: saved.__setitem__(provider, key)
    )
    return saved


def test_choosing_a_provider_a_model_and_a_setting_saves_them(here: dict[str, str]) -> None:
    ui = _Scripted(
        choices=["openai", "gpt-5.4-mini", "save", "temperature", "done", "project"],
        answers=["0.2"],
        secrets=["sk-typed-1234567890"],
    )
    path = Walkthrough(ui).run()
    assert path == Path.cwd() / "bi2.toml"
    saved = tomllib.loads(path.read_text(encoding="utf-8"))
    assert saved["ai"]["llm_model"] == "openai:gpt-5.4-mini"
    assert saved["ai"]["temperature"] == 0.2
    assert here == {"openai": "sk-typed-1234567890"}  # the key went to the keychain
    assert "sk-typed" not in path.read_text(encoding="utf-8")  # never to the file
    providers_shown = dict(ui.shown[0][1])
    assert "no key yet" in providers_shown["anthropic"]
    assert "no key needed" in providers_shown["ollama"]


def test_another_server_can_be_added_by_its_address(here: dict[str, str]) -> None:
    ui = _Scripted(
        choices=["+custom", "+typed", "done", "user"],
        answers=["myserver", "http://10.0.0.5/v1", "", "my-model"],
    )
    path = Walkthrough(ui).run()
    saved = tomllib.loads(path.read_text(encoding="utf-8"))
    assert saved["ai"]["llm_model"] == "myserver:my-model"
    assert saved["providers"]["myserver"]["base_url"] == "http://10.0.0.5/v1"
    assert saved["providers"]["myserver"]["needs_key"] is False


def test_a_backup_on_another_provider_and_no_jev(here: dict[str, str]) -> None:
    ui = _Scripted(
        choices=[
            "anthropic", "claude-haiku-5-5", "later",
            "backup_model", "pick", "gemini", "gemini-flash-lite-latest", "later",
            "jev", "no",
            "done", "project",
        ],
    )  # fmt: skip
    saved = tomllib.loads(Walkthrough(ui).run().read_text(encoding="utf-8"))
    assert saved["ai"]["llm_model"] == "anthropic:claude-haiku-5-5"
    assert saved["ai"]["backup_model"] == "gemini:gemini-flash-lite-latest"
    assert saved["ai"]["jev"] is False


def test_saving_keeps_what_the_file_already_holds(tmp_path: Path) -> None:
    path = tmp_path / "bi2.toml"
    path.write_text('[thresholds]\naccept = 0.9\n\n[ai]\nllm_model = "openai:gpt-5.4-nano"\n')
    save(path, {"ai": {"temperature": 0.5}, "models": {"openai:gpt-5.4-mini": {"per_minute": 900}}})
    saved = tomllib.loads(path.read_text(encoding="utf-8"))
    assert saved["thresholds"]["accept"] == 0.9
    assert saved["ai"] == {"llm_model": "openai:gpt-5.4-nano", "temperature": 0.5}
    assert saved["models"]["openai:gpt-5.4-mini"]["per_minute"] == 900


def test_toml_comes_back_as_it_went_in() -> None:
    data: dict[str, Any] = {
        "ai": {"llm_model": "ollama:llama3.1:8b", "llm": True, "temperature": 0.0},
        "providers": {"ollama": {"base_url": "http://gpu:11434/v1", "keys": ["A", "B"]}},
    }
    assert tomllib.loads(to_toml(data)) == data


def test_without_a_terminal_config_says_how_to_set_the_model_instead() -> None:
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 2
    assert "BI2_AI__LLM_MODEL" in result.output


def test_config_show_prints_every_setting_and_where_it_came_from() -> None:
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "ai.llm_model" in result.output
    assert "default" in result.output


def test_a_model_whose_provider_cant_be_told_stops_the_run_before_it_starts(
    tmp_path: Path,
) -> None:
    result = runner.invoke(
        app, ["analyze", "https://example.com", "--model", "llama3", "--out", str(tmp_path)]
    )
    assert result.exit_code == 2
    assert 'error: ai.llm_model: "llama3"' in result.output
    assert "ollama:llama3" in result.output  # how to name it
    assert "Traceback" not in result.output
    assert not (tmp_path / "results.jsonl").exists()


def test_doctor_reports_a_model_it_cant_use_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_checks(*args: object) -> dict[str, str]:
        return {}

    monkeypatch.setattr("bi2.cli.doctor._checks", no_checks)
    monkeypatch.setattr("bi2.cli.doctor._browser", lambda: "ok")
    monkeypatch.setattr("bi2.adapters.local.keys.keychain_key", lambda provider: None)
    monkeypatch.setenv("BI2_AI__LLM_MODEL", "llama3")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "can't be used" in result.output


def test_a_flag_changes_only_what_it_says(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "bi2.toml"
    project.write_text('[ai]\nllm_model = "openai:gpt-5.4-mini"\ntemperature = 0.4\n')
    monkeypatch.setattr("bi2.core.settings.config_files", lambda: [project])
    fast = run_settings(fast=True)
    assert fast.ai.llm is False
    assert fast.ai.llm_model == "openai:gpt-5.4-mini"  # the file's, untouched by --fast
    told = run_settings(model="anthropic:claude-haiku-5-5")
    assert told.ai.llm_model == "anthropic:claude-haiku-5-5"
    assert told.ai.temperature == 0.4
