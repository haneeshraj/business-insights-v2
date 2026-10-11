"""Implementations of the Decider port, which answers typed questions (yes/no, pick one, score)
with a probability for each answer.

- JevDecider calls Jev's REST API.
- LLMDecider asks the same questions through the LLM gateway, for users without a Jev key.
"""
