"""Fail the live eval when accuracy drops below its floor, or a site costs more than its
ceiling. Run by .github/workflows/eval.yml on the report `bi2 eval score --json` writes:

    python eval/check_scores.py scores.json [the most a site may cost, in US dollars]

The floors sit a few points under the scores on the gold set's saved pages, since live sites
change between visits and some block bots now and then. The cost ceiling is for the usual
models; a run on a pricier one can raise it.
"""

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

# The share of scored answers that must be right, by field.
FLOORS = {
    "company_name": 0.90,
    "logo": 0.75,
    "mcc": 0.85,
    "address": 0.45,
    "phone": 0.75,
    "social_links": 0.90,
}
# The most a site may cost on average, at list price, in US dollars.
MOST_PER_SITE = Decimal("0.005")


def _right_share(report: dict[str, Any], field: str) -> float | None:
    entry = next((f for f in report.get("fields", []) if f.get("field") == field), None)
    if entry is None or not entry.get("scored"):
        return None
    return float(entry["correct"]) / float(entry["scored"])


def main(scores: Path, most_per_site: Decimal = MOST_PER_SITE) -> int:
    report = json.loads(scores.read_text(encoding="utf-8"))
    failed = []
    for field, floor in FLOORS.items():
        share = _right_share(report, field)
        if share is None:
            continue
        verdict = "ok" if share >= floor else "BELOW THE FLOOR"
        print(f"{field:14} {share:6.1%}  floor {floor:.0%}  {verdict}")
        if share < floor:
            failed.append(field)
    sites = int(report.get("sites_run", 0)) or 1
    per_site = Decimal(str(report.get("cost", {}).get("usd", "0"))) / sites
    print(f"cost per site  ${per_site:.5f}  ceiling ${most_per_site}")
    if per_site > most_per_site:
        failed.append("cost per site")
    if failed:
        print("failed: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    ceiling = sys.argv[2].strip() if len(sys.argv) > 2 else ""
    sys.exit(main(Path(sys.argv[1]), Decimal(ceiling) if ceiling else MOST_PER_SITE))
