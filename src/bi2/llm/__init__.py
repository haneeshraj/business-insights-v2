"""The LLM gateway, one adapter per provider (Gemini, OpenAI, Anthropic), and the prompt loader.

Every model call goes through the gateway. It handles structured output, retries, caching and
the LLM-call log (tokens, cost, model and prompt version for each call).

Doesn't belong here: deciding what to ask a model, which is the job of the resolvers and the
Decider.
"""
