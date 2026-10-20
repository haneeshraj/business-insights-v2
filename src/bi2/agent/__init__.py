"""The investigator agent, for the fields the cascade couldn't settle from the site's own
pages. Today it's one step, `address_by_search` in resolvers/address.py: a web search through
Gemini's Google Search grounding, whose answer must cite its pages. A tool-using loop with a
fixed call budget belongs here, when a field needs more than one search.
"""
