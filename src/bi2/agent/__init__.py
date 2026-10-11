"""The investigator agent. It handles the fields the cascade couldn't settle, using a small set
of read-only tools and a fixed tool-call budget.

Belongs here: the agent loop and its tool definitions.

Doesn't belong here: the normal path for a field, which is a fixed workflow in resolvers/.
"""
