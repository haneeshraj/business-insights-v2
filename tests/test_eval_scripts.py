"""Tests for the scripts in eval/ that CI runs."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "eval" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(tmp_path: Path, correct: int, usd: str) -> Path:
    report = {
        "fields": [{"field": "mcc", "scored": 10, "correct": correct}],
        "sites_run": 10,
        "cost": {"usd": usd},
    }
    path = tmp_path / "scores.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_the_live_eval_passes_above_the_floors_and_under_the_ceiling(tmp_path: Path) -> None:
    check = _script("check_scores")
    assert check.main(_report(tmp_path, correct=9, usd="0.01")) == 0


def test_the_live_eval_fails_below_a_floor_or_over_the_ceiling(tmp_path: Path) -> None:
    check = _script("check_scores")
    assert check.main(_report(tmp_path, correct=5, usd="0.01")) == 1  # MCC at 50%
    assert check.main(_report(tmp_path, correct=9, usd="1.00")) == 1  # $0.10 a site
