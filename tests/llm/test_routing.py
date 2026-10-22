"""Tests for chaining LLMs across providers, and sending web searches to the model that can."""

import pytest

from bi2.core.asking import Generated, Prompt
from bi2.core.errors import BudgetUsedUp, ModelUnavailable
from bi2.llm.routing import Fallback, Searching

PROMPT = Prompt(task="t", version="1", instructions="Answer.", evidence="x", answer_schema={})


class _Model:
    def __init__(self, name: str, fails: ModelUnavailable | None = None) -> None:
        self.name = name
        self.asked: list[Prompt] = []
        self._fails = fails

    async def generate(self, prompt: Prompt) -> Generated:
        self.asked.append(prompt)
        if self._fails is not None:
            raise self._fails
        return Generated(data={"by": self.name}, model=self.name)


async def test_the_backup_answers_when_the_first_model_cant() -> None:
    first = _Model("openai", ModelUnavailable("down"))
    backup = _Model("gemini")
    chain = Fallback([first, backup])
    assert chain.name == "openai"
    assert (await chain.generate(PROMPT)).data == {"by": "gemini"}


async def test_a_chain_out_of_budget_everywhere_says_so() -> None:
    used_up = Fallback([_Model("a", BudgetUsedUp("a's day")), _Model("b", BudgetUsedUp("b's"))])
    with pytest.raises(BudgetUsedUp, match="a's day"):
        await used_up.generate(PROMPT)
    mixed = Fallback([_Model("a", BudgetUsedUp("a's day")), _Model("b", ModelUnavailable("down"))])
    with pytest.raises(ModelUnavailable) as raised:
        await mixed.generate(PROMPT)
    assert not isinstance(raised.value, BudgetUsedUp)
    with pytest.raises(ValueError, match="at least one"):
        Fallback([])


async def test_web_searches_go_to_the_search_model_and_the_rest_to_the_main_one() -> None:
    main, search = _Model("anthropic"), _Model("gemini")
    router = Searching(main, search)
    assert (await router.generate(PROMPT)).data == {"by": "anthropic"}
    searched = PROMPT.model_copy(update={"search": True})
    assert (await router.generate(searched)).data == {"by": "gemini"}
    assert router.name == "anthropic"
