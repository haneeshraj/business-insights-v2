"""How far v2's "sure" can be trusted: for each field, how many answers it kept as sure, and how
many of those were wrong, judged by people's checks, drafted checks and the gold set, the way
`bi2 eval compare` judges them. Prints a Markdown table:

    python eval/calibration.py bi2-results/<run> eval/<gold or test-set>.toml
"""

import sys
from collections import Counter
from pathlib import Path

from bi2.core.models import SiteResult
from bi2.evaluation.gold import load_gold_set, site_key
from bi2.evaluation.learning import Outcome, label_answers
from bi2.evaluation.verifications import load_verifications


def main(run: Path, gold_file: Path) -> None:
    lines = (run / "results.jsonl").read_text(encoding="utf-8").splitlines()
    results = [SiteResult.model_validate_json(line) for line in lines if line.strip()]
    gold = {site_key(site.url): site for site in load_gold_set(gold_file).sites}
    checks = load_verifications(Path("eval/verifications.jsonl"))
    drafts = load_verifications(Path("eval/drafted-checks.jsonl"))
    tally: dict[str, Counter[Outcome]] = {}
    for label in label_answers(results, gold, checks, drafts):
        tally.setdefault(label.field, Counter())[label.outcome] += 1
    print("| Field | Checked | Kept as sure | Sure but wrong | Unsure, sent on |")
    print("|---|---|---|---|---|")
    for field, counts in tally.items():
        kept = counts[Outcome.TRUE_POSITIVE] + counts[Outcome.FALSE_POSITIVE]
        sent = counts[Outcome.FALSE_NEGATIVE] + counts[Outcome.TRUE_NEGATIVE]
        wrong = counts[Outcome.FALSE_POSITIVE]
        share = f" ({wrong / kept:.1%})" if kept else ""
        print(f"| {field} | {kept + sent} | {kept} | {wrong}{share} | {sent} |")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
