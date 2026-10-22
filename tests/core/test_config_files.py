"""Tests for the layers settings come in: defaults, config files, the environment, flags."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from bi2.core.providers import ModelRef
from bi2.core.settings import Keys, Settings, keys_from_environment, where_set
from bi2.llm.registry import model_info


@pytest.fixture
def files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A project file and a user file, the only config files read."""
    project, user = tmp_path / "bi2.toml", tmp_path / "user" / "bi2.toml"
    user.parent.mkdir()
    monkeypatch.setattr("bi2.core.settings.config_files", lambda: [project, user])
    monkeypatch.setattr("bi2.core.settings.project_config_file", lambda: project)
    monkeypatch.setattr("bi2.core.settings.user_config_file", lambda: user)
    return project, user


def test_each_layer_overrides_the_ones_before_it(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, user = files
    user.write_text('[ai]\nllm_model = "anthropic:claude-haiku-5-5"\ntemperature = 0.3\n')
    assert Settings().ai.llm_model == "anthropic:claude-haiku-5-5"
    project.write_text('[ai]\nllm_model = "openai:gpt-5.4-mini"\n')
    settings = Settings()
    assert settings.ai.llm_model == "openai:gpt-5.4-mini"  # the project's file wins
    assert settings.ai.temperature == 0.3  # what it doesn't say comes from the user's
    monkeypatch.setenv("BI2_AI__LLM_MODEL", "groq:llama-3.3-70b-versatile")
    assert Settings().ai.llm_model == "groq:llama-3.3-70b-versatile"
    told = Settings(ai={"llm_model": "ollama:llama3.1"})  # type: ignore[arg-type]
    assert told.ai.llm_model == "ollama:llama3.1"
    assert told.ai.temperature == 0.3  # a flag changes only what it says


def test_an_empty_variable_counts_as_unset(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _ = files
    project.write_text('[ai]\nllm_model = "openai:gpt-5.4-mini"\n')
    monkeypatch.setenv("BI2_AI__LLM_MODEL", "")  # like a CI input left empty
    assert Settings().ai.llm_model == "openai:gpt-5.4-mini"
    monkeypatch.setenv("BI2_AI__BACKUP_MODEL", "none")  # so this is how to say there's none
    assert Settings().ai.backup_model == ""


def test_the_llms_named_and_what_is_wrong_with_a_name() -> None:
    told = Settings(ai={"llm_model": "claude-haiku-5-5", "search_model": "gemini-3.5-flash"})  # type: ignore[arg-type]
    assert told.llm_models() == {
        "llm_model": ModelRef("anthropic", "claude-haiku-5-5"),
        "backup_model": ModelRef("gemini", "gemini-3.5-flash"),
        "search_model": ModelRef("gemini", "gemini-3.5-flash"),
    }
    unknown = Settings(ai={"backup_model": "llama3"})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"ai\.backup_model: .*ollama:llama3"):
        unknown.llm_models()
    jev = Settings(ai={"llm_model": "jev-latest"})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Jev, the Decider"):
        jev.llm_models()


def test_a_provider_can_be_changed_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Like a Docker container reaching the Ollama on its host.
    monkeypatch.setenv("BI2_PROVIDERS__OLLAMA__BASE_URL", "http://host.docker.internal:11434/v1")
    ollama = Settings().all_providers()["ollama"]
    assert ollama.base_url == "http://host.docker.internal:11434/v1"
    assert ollama.local  # the rest stays as listed


def test_a_file_that_begins_with_a_byte_order_mark_is_read(files: tuple[Path, Path]) -> None:
    project, _ = files
    # As Windows PowerShell's Set-Content -Encoding utf8 saves it.
    project.write_bytes(b'\xef\xbb\xbf[ai]\r\nllm_model = "openai:gpt-5.4-mini"\r\n')
    settings = Settings()
    assert settings.ai.llm_model == "openai:gpt-5.4-mini"
    sources = {name: source for name, _, source in where_set(settings)}
    assert sources["ai.llm_model"].startswith("this folder's file")


def test_a_file_gives_a_model_its_own_prices_and_limits(files: tuple[Path, Path]) -> None:
    project, _ = files
    project.write_text(
        '[models."openai:gpt-5.4-mini"]\nper_minute = 900\n\n'
        '[models."groq:llama-3.3-70b-versatile"]\ninput_per_million = 0.59\n'
    )
    settings = Settings()
    listed = model_info(ModelRef("openai", "gpt-5.4-mini"), settings.models)
    assert listed.per_minute == 900
    assert listed.input_per_million == Decimal("0.75")  # unchanged
    unlisted = model_info(ModelRef("groq", "llama-3.3-70b-versatile"), settings.models)
    assert unlisted.input_per_million == Decimal("0.59")
    assert not unlisted.listed
    free = model_info(ModelRef("ollama", "llama3.1"))
    assert free.input_per_million == 0
    assert free.per_minute == 60


def test_where_each_setting_came_from(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, user = files
    user.write_text("[ai]\ntemperature = 0.2\n")
    project.write_text('[ai]\nllm_model = "openai:gpt-5.4-mini"\n')
    monkeypatch.setenv("BI2_AI__CALLS_PER_SITE", "5")
    sources = {name: source for name, _, source in where_set(Settings())}
    assert sources["ai.llm_model"].startswith("this folder's file")
    assert sources["ai.temperature"] == "your config file"
    assert sources["ai.calls_per_site"] == "environment (BI2_AI__CALLS_PER_SITE)"
    assert sources["ai.timeout_s"] == "default"


def test_keys_come_from_each_providers_usual_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "JEV_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("GROQ_API_KEY", "  ")  # set but empty: not a key
    keys = keys_from_environment()
    assert keys.get("openai") == SecretStr("sk-openai")
    assert keys.get("anthropic") == SecretStr("sk-ant")
    assert keys.get("groq") is None
    assert keys.gemini is None


def test_keys_can_be_given_by_provider_and_added_to() -> None:
    keys = Keys(gemini=SecretStr("g"), jev=SecretStr("j"))  # type: ignore[call-arg]
    assert keys.gemini == SecretStr("g")
    more = keys.with_key("openai", SecretStr("o"))
    assert more.get("openai") == SecretStr("o")
    assert more.get("gemini") == SecretStr("g")
    assert keys.get("openai") is None  # the first stays as it was
