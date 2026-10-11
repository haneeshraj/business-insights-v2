# Contributing

Thanks for helping. This guide covers setup and the checks. [docs/codebase.md](docs/codebase.md) explains where code goes and how to write it, and [docs/architecture.md](docs/architecture.md) explains what v2 does and why.

## Setup

1. Install [uv](https://docs.astral.sh/uv/).
2. Clone the repository, then run these in its folder:

   ```
   uv sync                      # creates .venv with the package and the dev tools
   uv run pre-commit install    # runs the checks before each commit
   ```

Development uses Python 3.12, the oldest version v2 supports (see `.python-version`). uv installs it if you don't have it.

## Checks

CI runs all of these on every pull request. None of them need network access or API keys.

```
uv run ruff check        # lint
uv run ruff format       # format
uv run mypy              # strict type checking
uv run lint-imports      # the layer rules
uv run pytest            # tests
```

Tests that need network access and API keys are marked `live` and are skipped unless you run `uv run pytest -m live`.

## The rules that matter most

- **Respect the layers** described in docs/codebase.md. import-linter enforces them.
- **Name modules after their topic.** There is no `utils.py`, `helpers.py` or `misc.py`.
- **Library code never prints.** It emits events, and the terminal app decides how to show them.
- **Only `core/settings.py` reads environment variables.**
- **Every new dependency needs a one-line reason** in the dependency table in docs/codebase.md.
- **Keys never go in files.**

## Pull requests

- Keep each pull request to one change, with tests.
- If you change a prompt, a model or a threshold, say so in the description. A maintainer will run the live eval and post the scores before merging.
- Update the docs when behavior or structure changes.
