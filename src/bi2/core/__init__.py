"""Building blocks shared by the whole package: data models, the interfaces ("ports") for
everything that does I/O, the RunContext, errors, settings, progress events and small pure
helpers.

Belongs here: code that two or more packages need and that does no I/O. The one exception is
settings.py, which reads the config files and the environment.

Doesn't belong here: anything that touches the network, the browser or a model provider, and
helpers that only one package uses. core imports nothing else from bi2.
"""
