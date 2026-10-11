# v1 baseline

Measures v1 on the gold set, so v2's numbers have something to beat. It takes three commands, run from the v2 repository. These assume v1 is cloned next to it, in `../business-insights`.

**1. Make an environment for v1.** v1 pins older library versions than v2, so it gets its own:

```
uv venv eval/baselines/v1/.venv --python 3.12
uv pip install --python eval/baselines/v1/.venv -r ../business-insights/requirements.txt
```

**2. Run v1 on the gold set.** This needs `GEMINI_API_KEY` (and optionally `SERPAPI_KEY`) in the environment, Google Chrome installed, and about a minute per site. It costs money on your keys.

```
eval/baselines/v1/.venv/Scripts/python eval/baselines/v1/run_v1.py --v1 ../business-insights --gold eval/gold.toml --out v1-raw.jsonl
```

On macOS and Linux, the Python is `eval/baselines/v1/.venv/bin/python`. Add `--limit 3` for a quick trial. If the model in v1's `config.yaml` has been retired, add `--model` with a current Gemini model.

**3. Convert and score.** Look up the model's current prices, in US dollars per million tokens:

```
uv run python eval/baselines/v1/convert.py v1-raw.jsonl v1-results.jsonl --input-price 0.30 --output-price 2.50
uv run bi2 eval score eval/gold.toml v1-results.jsonl
```

## What's different from running v1 normally

- **Every model call is counted.** v1's own reports counted tokens only for its first call. For Gemini, the counts come from the SDK and include thinking tokens.
- **No fixed sleep between sites.** v1's 10-second pause after each site is turned off. Its 5-second wait for each page to load stays, because it's part of how v1 works.
- **v1's copies of each page go to a temporary folder**, not into either repository.
- **v1's answers are recorded as given.** That includes the MCC 5812 ("restaurant") it reports when its model calls fail, so the baseline shows v1 as it really behaves.
