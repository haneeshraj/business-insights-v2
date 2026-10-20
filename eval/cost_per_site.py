"""What a site costs and how long it takes, from a run's model-call log and results, and what
the same calls would cost on other providers' models. Prints Markdown tables:

    python eval/cost_per_site.py bi2-results/<run>

Token counts are the run's own. For an LLM standing in for Jev, each decision costs the same
input plus the instructions that turn it into a JSON question (about 250 tokens), and about 40
output tokens a question. Prices are list prices per million tokens, as of 2026-10-20.
"""

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

# (input, output) US dollars per million tokens.
PRICES = {
    "Jev (TypeSafe)": (0.042, 0.0),
    "Gemini 3.5 Flash-Lite": (0.30, 2.50),
    "Gemini 3.6 Flash": (0.75, 3.75),
    "Gemini 3.1 Pro": (2.00, 12.00),
    "Claude Haiku 5.5": (0.10, 0.50),
    "Claude Sonnet 5.5": (2.00, 10.00),
    "Claude Opus 5.5": (4.00, 20.00),
    "GPT-5.4 nano": (0.20, 1.25),
    "GPT-5.4 mini": (0.75, 4.50),
}
_LLM_DECISION_EXTRA_IN, _LLM_DECISION_OUT = 250, 40


def _calls(run: Path) -> list[dict[str, object]]:
    lines = (run / "model-calls.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _results(run: Path) -> list[dict[str, object]]:
    lines = (run / "results.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def main(run: Path) -> None:
    calls = [c for c in _calls(run) if not c["problem"]]
    results = _results(run)
    sites = len(results) or 1
    jev = [c for c in calls if c["who"] == "jev"]
    gemini = [c for c in calls if c["who"] == "gemini"]
    tokens = lambda cs, key: sum(int(c[key]) for c in cs)  # noqa: E731
    jev_in, gem_in, gem_out = (
        tokens(jev, "input_tokens"),
        tokens(gemini, "input_tokens"),
        tokens(gemini, "output_tokens"),
    )
    questions = len(jev)
    print(
        f"## {run.name}: {sites} sites, {len(calls)} model calls ({len(jev)} Jev, {len(gemini)} Gemini)\n"
    )
    print("| | Per site |")
    print("|---|---|")
    print(
        f"| Model calls | {len(calls) / sites:.2f} ({len(jev) / sites:.2f} Jev, {len(gemini) / sites:.2f} Gemini) |"
    )
    print(f"| Jev input tokens | {jev_in / sites:,.0f} |")
    print(f"| Gemini tokens in / out | {gem_in / sites:,.0f} / {gem_out / sites:,.0f} |")
    seconds = [float(r["seconds"]) for r in results if not r.get("error")]
    if seconds:
        print(
            f"| Time, median / 90th percentile | {statistics.median(seconds):.1f} s / {statistics.quantiles(seconds, n=10)[-1]:.1f} s |"
        )
    by_task: dict[str, list[float]] = defaultdict(list)
    for c in calls:
        if not c["cached"]:
            by_task[f"{c['who']} {c['task']}"].append(float(c["seconds"]))
    if by_task:
        print("\n| Call | Count | Median time |")
        print("|---|---|---|")
        for task, times in sorted(by_task.items()):
            print(f"| {task} | {len(times)} | {statistics.median(times):.1f} s |")
    print("\n| Models | Per site | Per 1,000 sites |")
    print("|---|---|---|")
    jev_price = PRICES["Jev (TypeSafe)"]
    for name, (inp, out) in PRICES.items():
        if name.startswith("Jev"):
            continue
        # Jev for decisions and this model for generations, as bi2 runs by default ...
        with_jev = (jev_in * jev_price[0] + gem_in * inp + gem_out * out) / 1e6 / sites
        # ... and this model alone, standing in for Jev too.
        alone_in = jev_in + questions * _LLM_DECISION_EXTRA_IN + gem_in
        alone_out = questions * _LLM_DECISION_OUT + gem_out
        alone = (alone_in * inp + alone_out * out) / 1e6 / sites
        print(f"| Jev + {name} | ${with_jev:.5f} | ${with_jev * 1000:.2f} |")
        print(f"| {name} alone | ${alone:.5f} | ${alone * 1000:.2f} |")
    statuses: dict[str, Counter[str]] = defaultdict(Counter)
    for r in results:
        for field in ("company_name", "logo", "mcc", "address", "phone", "email", "social_links"):
            value = r.get(field)
            if isinstance(value, dict):
                statuses[field][str(value["status"])] += 1
    print("\n| Field | ok | needs review | not found | error |")
    print("|---|---|---|---|---|")
    for field, counts in statuses.items():
        print(
            f"| {field} | {counts['ok']} | {counts['needs_review']} | {counts['not_found']} | {counts['error']} |"
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
