"""Tests for which LLM and Decider a run gets, from its settings and the keys it has."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from bi2.core.settings import Keys, Settings
from bi2.decide.llm import LlmDecider, WithBackup
from bi2.llm.anthropic import Anthropic
from bi2.llm.gemini import Gemini
from bi2.llm.openai_compatible import OpenAICompatible
from bi2.llm.routing import Fallback, Searching
from bi2.wiring import local_context


async def _models(tmp_path: Path, ai: dict[str, Any], **keys: str) -> tuple[Any, Any, Any]:
    secrets = Keys(llm={k: SecretStr(v) for k, v in keys.items() if k != "jev"},
                   jev=SecretStr(keys["jev"]) if "jev" in keys else None)  # fmt: skip
    settings = Settings(ai=ai)  # type: ignore[arg-type]
    async with local_context(tmp_path, load_pages=False, keys=secrets, settings=settings) as ctx:
        return ctx.llm, ctx.decider, ctx.second


async def test_any_provider_can_be_the_llm(tmp_path: Path) -> None:
    llm, decider, second = await _models(
        tmp_path, {"llm_model": "openai:gpt-5.4-mini", "backup_model": ""}, openai="sk"
    )
    assert isinstance(llm, OpenAICompatible)
    assert llm.name == "openai"
    assert isinstance(decider, LlmDecider)  # with no Jev key, the LLM makes the choices too
    assert second is None
    claude, _, _ = await _models(
        tmp_path, {"llm_model": "claude-haiku-5-5", "backup_model": ""}, anthropic="sk"
    )
    assert isinstance(claude, Anthropic)


async def test_a_backup_on_another_provider_makes_a_chain(tmp_path: Path) -> None:
    llm, decider, second = await _models(
        tmp_path,
        {"llm_model": "openai:gpt-5.4-mini", "backup_model": "gemini-3.5-flash"},
        openai="sk",
        gemini="g",
        jev="j",
    )
    assert isinstance(llm, Fallback)
    assert isinstance(decider, WithBackup)  # Jev, with the LLM behind it
    assert isinstance(second, LlmDecider)


async def test_two_gemini_models_share_one_client(tmp_path: Path) -> None:
    llm, _, _ = await _models(tmp_path, {}, gemini="g")  # the defaults
    assert isinstance(llm, Gemini)


async def test_web_searches_can_go_to_gemini_whatever_the_llm(tmp_path: Path) -> None:
    llm, _, _ = await _models(
        tmp_path,
        {"llm_model": "anthropic:claude-haiku-5-5", "backup_model": "", "search_model": "gemini-3.5-flash"},
        anthropic="sk",
        gemini="g",
    )  # fmt: skip
    assert isinstance(llm, Searching)


async def test_a_model_without_its_key_is_left_out_but_a_local_one_needs_none(
    tmp_path: Path,
) -> None:
    llm, decider, _ = await _models(
        tmp_path, {"llm_model": "openai:gpt-5.4-mini", "backup_model": ""}
    )
    assert llm is None
    assert decider is None
    local, _, _ = await _models(tmp_path, {"llm_model": "ollama:llama3.1", "backup_model": ""})
    assert isinstance(local, OpenAICompatible)


async def test_jev_can_leave_the_choices_to_the_llm(tmp_path: Path) -> None:
    _, decider, _ = await _models(tmp_path, {"jev": False}, gemini="g", jev="j")
    assert isinstance(decider, LlmDecider)


async def test_jev_isnt_an_llm(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Decider"):
        await _models(tmp_path, {"llm_model": "jev-latest"}, jev="j")
