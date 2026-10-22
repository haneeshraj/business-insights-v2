"""Tests for naming a model on a provider, and the providers a config file adds or changes."""

import pytest

from bi2.core.providers import JEV, ModelRef, parse_model, providers


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("openai:gpt-5.4-mini", ModelRef("openai", "gpt-5.4-mini")),
        ("anthropic:claude-haiku-5-5", ModelRef("anthropic", "claude-haiku-5-5")),
        ("ollama:llama3.1:8b", ModelRef("ollama", "llama3.1:8b")),  # Ollama's tags have colons
        ("gemini-flash-lite-latest", ModelRef("gemini", "gemini-flash-lite-latest")),  # listed
        ("claude-sonnet-5-5", ModelRef("anthropic", "claude-sonnet-5-5")),
        ("gpt-4.1-mini", ModelRef("openai", "gpt-4.1-mini")),  # unlisted, but its name says
        ("o4-mini", ModelRef("openai", "o4-mini")),
        ("mistral-small-latest", ModelRef("mistral", "mistral-small-latest")),
        ("grok-4", ModelRef("xai", "grok-4")),
        ("deepseek-chat", ModelRef("deepseek", "deepseek-chat")),
        ("jev-latest", ModelRef(JEV, "jev-latest")),
    ],
)
def test_a_model_is_named_by_its_provider_or_its_own_name(name: str, expected: ModelRef) -> None:
    assert parse_model(name) == expected
    assert str(expected).count(":") >= 1


def test_a_name_that_doesnt_say_whose_it_is_is_refused_with_how_to_name_it() -> None:
    with pytest.raises(ValueError, match=r'"ollama:llama3\.1"') as refused:
        parse_model("llama3.1")
    assert "openai" in str(refused.value)  # the providers are listed
    with pytest.raises(ValueError, match="no model"):
        parse_model("  ")


def test_a_config_file_changes_a_provider_field_by_field_and_adds_new_ones() -> None:
    found = providers(
        {
            "ollama": {"base_url": "http://gpu-box:11434/v1"},
            "myserver": {"title": "My server", "base_url": "http://10.0.0.5/v1", "json": "object"},
        }
    )
    assert found["ollama"].base_url == "http://gpu-box:11434/v1"
    assert found["ollama"].needs_key is False  # kept from data/providers.toml
    assert found["ollama"].local
    assert found["myserver"].api == "openai"
    assert found["myserver"].json_mode == "object"
    assert parse_model("myserver:my-model", found) == ModelRef("myserver", "my-model")


def test_the_big_three_and_the_usual_others_are_built_in() -> None:
    found = providers()
    for name in ("gemini", "anthropic", "openai", "mistral", "groq", "openrouter", "ollama"):
        assert name in found
    assert found["anthropic"].api == "anthropic"
    assert found["gemini"].api == "gemini"
    assert found["openai"].token_param == "max_completion_tokens"
    assert "OPENAI_API_KEY" in found["openai"].keys
