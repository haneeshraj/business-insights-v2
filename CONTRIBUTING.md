# Contributing

Thanks for helping. This guide covers setup and the checks. [docs/codebase.md](docs/codebase.md) explains where code goes and how to write it, and [docs/architecture.md](docs/architecture.md) explains what v2 does and why.

## Setup

1. Install [uv](https://docs.astral.sh/uv/).
2. Clone the repository, then run these in its folder:

   ```
   uv sync                              # creates .venv with the package and the dev tools
   uv run pre-commit install            # runs the checks before each commit
   uv run playwright install chromium   # the browser that loads pages; its tests need it
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

## Trying one part on real sites

`bi2 dev` runs one part of the pipeline on real websites, so a change can be checked on its own. What it saves goes in `bi2-results/`, which git ignores.

```
uv run bi2 dev fetch https://example.com        # load a page, show what the browser captured
uv run bi2 dev fetch --gold eval/gold.toml      # load every gold-set site and save the pages
uv run bi2 dev evidence https://example.com     # show the evidence taken from a page
uv run bi2 dev evidence --saved bi2-results/dev/fetch --gold eval/gold.toml
```

The last one rebuilds the evidence of saved pages without loading them again, and counts how many of the gold set's answers the evidence already holds. Run it before and after changing an extractor.

`bi2 dev evidence` also writes `report.html` next to the evidence: one page per run with every site's screenshot, its evidence, its logo candidates as pictures, and its gold-set checks. Add `--open` to open it in your browser.

## Analyzing sites

`bi2 analyze` runs the whole pipeline and writes one result per site:

```
uv run bi2 analyze https://example.com                    # one or more sites, loaded live
uv run bi2 analyze --gold eval/gold.toml                  # every gold-set site, checked against it
uv run bi2 analyze --saved bi2-results/dev/fetch --gold eval/gold.toml   # saved pages, offline
uv run bi2 eval score eval/gold.toml bi2-results/analyze/results.jsonl   # accuracy by field
```

Results go to `bi2-results/analyze/`: `results.jsonl` with every site, a folder per site with its result, evidence, screenshot and logo, and `report.html` with the answers next to the evidence.

## Checking answers

`bi2 review` opens the last run's report in your browser with a check on every answer:

```
uv run bi2 review                      # the results in bi2-results/analyze
uv run bi2 review path/to/results      # another run
```

Press Right or Wrong, and add a note about what you saw. For an answer where nothing was found, Right means there's nothing to find. Each check is saved to `eval/verifications.jsonl` straight away, and the summary at the top updates: how many answers fall in each of the four groups, and how often each field was right at each confidence. Where your check and the gold set disagree, yours counts. The page is served from your machine only, and Ctrl+C in the terminal stops it.

## The rules that matter most

- **Respect the layers** described in docs/codebase.md. import-linter enforces them.
- **Name modules after their topic.** There is no `utils.py`, `helpers.py` or `misc.py`.
- **Library code never prints.** It emits events, and the terminal app decides how to show them.
- **Only `core/settings.py` reads environment variables.**
- **Every new dependency needs a one-line reason** in the dependency table in docs/codebase.md.
- **Keys never go in files.**

## Commit messages

Each commit message is a type and a short summary, for example `feat: json-ld evidence extractor`. Pick the type by what the change is:

| Type | For |
|---|---|
| `feat:` | new behavior |
| `fix:` | a bug fix |
| `docs:` | documentation only |
| `refactor:` | restructuring with no behavior change |
| `test:` | adding or changing tests |
| `ci:` | CI workflows |
| `build:` | packaging and dependencies (`pyproject.toml`, `uv.lock`) |
| `chore:` | maintenance that fits nowhere else |
| `perf:` | speed or cost improvements |
| `style:` | formatting only |
| `revert:` | undoing an earlier commit |
| `init:` | initial setup |

Keep the summary short. A longer body isn't needed.

## Pull requests

- Keep each pull request to one change, with tests.
- If you change a prompt, a model or a threshold, say so in the description. A maintainer will run the live eval and post the scores before merging.
- Update the docs when behavior or structure changes.
