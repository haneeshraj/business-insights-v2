"""v2's MCP server, so AI assistants like Claude can look businesses up with it.

It runs on the user's own machine, with the user's own keys, the same way the terminal app
does: an entry point like the CLI, building a RunContext and calling the pipeline. Installed
with the `mcp` extra: `pip install "business-insights[mcp]"`, then `bi2 mcp`.
"""
