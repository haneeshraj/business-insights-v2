"""`bi2 eval check`: how often the checker agrees with the gold set and people's checks."""

import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from bi2.adapters.local.answers import CallLog
from bi2.cli.analyze import app_folder
from bi2.core.models import Evidence, SiteResult
from bi2.evaluation.gold import load_gold_set, site_key
from bi2.evaluation.scoring import Verdict, score_site
from bi2.resolvers.checking import CHECKED_FIELDS, check_answers
from bi2.wiring import local_context


async def _check_all(
    run: Path, share: float, answers: Path
) -> list[tuple[SiteResult, dict[str, float]]]:
    folders = await asyncio.to_thread(
        lambda: sorted(p for p in run.iterdir() if (p / "evidence.json").is_file())
    )
    found = []
    async with local_context(
        run / "checks",
        load_pages=False,
        kept_answers=answers,
        call_log=CallLog(run / "check-calls.jsonl"),
        usage_file=app_folder() / "free-tier-usage.json",
    ) as ctx:
        for folder in folders:
            result_text = await asyncio.to_thread((folder / "result.json").read_text, "utf-8")
            evidence_text = await asyncio.to_thread((folder / "evidence.json").read_text, "utf-8")
            result = SiteResult.model_validate_json(result_text)
            ev = Evidence.model_validate_json(evidence_text)
            found.append((result, await check_answers(result, ev, ctx, share=share)))
    return found


def check(
    run: Annotated[
        Path,
        typer.Argument(
            help="A run's results folder, from bi2 analyze.", exists=True, file_okay=False
        ),
    ],
    gold: Annotated[
        Path,
        typer.Option(help="The gold file to judge the checker by.", exists=True, dir_okay=False),
    ],
    share: Annotated[
        float, typer.Option(help="The share of sure answers to check; 1 checks all.")
    ] = 1.0,
) -> None:
    """Ask the checker about a run's sure answers, and say how often it agrees with the gold set
    and people's checks. A checker worth trusting flags the wrong answers and few right ones."""
    sites = {site_key(entry.url): entry for entry in load_gold_set(gold).sites}
    checked = asyncio.run(_check_all(run, share, app_folder() / "answers"))
    table = Table(title="The checker against the gold set and people's checks")
    for column in (
        "Field",
        "Checked",
        "Agrees, right",
        "Flags, wrong",
        "Flags, right",
        "Agrees, wrong",
    ):
        table.add_column(column, justify="left" if column == "Field" else "right")
    counts: dict[str, Counter[str]] = {field: Counter() for field in CHECKED_FIELDS}
    for result, probabilities in checked:
        entry = sites.get(site_key(result.page.url))
        verdicts = {s.field: s.verdict for s in score_site(entry, result)} if entry else {}
        for field, probability in probabilities.items():
            verdict = verdicts.get(field)
            if verdict not in (Verdict.CORRECT, Verdict.WRONG):
                continue
            right = verdict is Verdict.CORRECT
            agrees = probability >= 0.5
            counts[field][
                ("agrees" if agrees else "flags") + (", right" if right else ", wrong")
            ] += 1
    for field, count in counts.items():
        total = sum(count.values())
        if total:
            table.add_row(
                field,
                str(total),
                *(
                    str(count[k])
                    for k in ("agrees, right", "flags, wrong", "flags, right", "agrees, wrong")
                ),
            )
    Console().print(table)
    (run / "checks.json").write_text(
        json.dumps([{"url": r.page.url, "checks": p} for r, p in checked if p], indent=2),
        encoding="utf-8",
    )
