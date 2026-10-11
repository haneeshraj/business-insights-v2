"""The terminal app: Typer commands, the interactive session, Rich display, and the output
writers (table, JSON, JSONL, CSV).

Belongs here: turning what the user types into pipeline runs, and showing progress events and
results.

Doesn't belong here: analysis logic. The terminal app builds a RunContext through wiring.py and
calls the pipeline.
"""
