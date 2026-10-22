"""Putting LLMs together: a chain that asks the next model when one can't answer, and a router
that sends web searches to the model that can do them."""

from collections.abc import Sequence

from bi2.core.asking import Generated, Prompt
from bi2.core.errors import BudgetUsedUp, ModelUnavailable
from bi2.core.ports import LanguageModel


class Fallback:
    """Asks each model in turn until one answers: the model, then its backup, which can be on
    another provider."""

    def __init__(self, models: Sequence[LanguageModel]) -> None:
        if not models:
            raise ValueError("a fallback needs at least one model")
        self._models = list(models)
        self.name = self._models[0].name

    async def generate(self, prompt: Prompt) -> Generated:
        """The first answer that comes. Raises ModelUnavailable when no model answers, and
        BudgetUsedUp when that's because every model's quota is used up."""
        problems: list[ModelUnavailable] = []
        for model in self._models:
            try:
                return await model.generate(prompt)
            except ModelUnavailable as exc:
                problems.append(exc)
        why = "; ".join(str(problem) for problem in problems)
        if all(isinstance(problem, BudgetUsedUp) for problem in problems):
            raise BudgetUsedUp(why)
        raise ModelUnavailable(why)


class Searching:
    """Sends the prompts that search the web to the model that can, and the rest to the main
    one: an Anthropic or OpenAI model reads the pages, and Gemini searches."""

    def __init__(self, main: LanguageModel, search: LanguageModel) -> None:
        self._main = main
        self._search = search
        self.name = main.name

    async def generate(self, prompt: Prompt) -> Generated:
        return await (self._search if prompt.search else self._main).generate(prompt)
