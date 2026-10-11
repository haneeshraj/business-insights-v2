"""Run v1 on the gold set's sites and save what it returns, with every model call counted.

This runs in v1's own environment; see README.md. v1 counted tokens for only one of its model
calls, so this counts all of them. It also turns off v1's fixed sleep after each site.
"""

import argparse
import json
import os
import sys
import tempfile
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _count_model_calls(calls: list[dict[str, Any]], phase: dict[str, str]) -> None:
    """Record tokens for every model call. Gemini counts come straight from the SDK, so they
    include thinking tokens, which v1's own usage numbers leave out."""
    from utils.llm import LLMClient  # v1

    try:
        from google.genai import models as genai_models
    except ImportError:
        genai_models = None

    if genai_models is not None:
        original_generate = genai_models.Models.generate_content

        def generate_content(self: Any, *args: Any, **kwargs: Any) -> Any:
            response = original_generate(self, *args, **kwargs)
            usage = response.usage_metadata
            thinking = (getattr(usage, "thoughts_token_count", None) or 0) if usage else 0
            calls.append(
                {
                    "phase": phase["name"],
                    "model": str(kwargs.get("model", "")),
                    "input_tokens": (usage.prompt_token_count or 0) if usage else 0,
                    "output_tokens": ((usage.candidates_token_count or 0) + thinking)
                    if usage
                    else 0,
                }
            )
            return response

        genai_models.Models.generate_content = generate_content

    original_query = LLMClient.query

    def query(self: Any, model: str, *args: Any, **kwargs: Any) -> Any:
        response = original_query(self, model, *args, **kwargs)
        if self._detect_provider(model) != "google":  # Gemini calls are counted above
            usage = response.get("usage", {})
            calls.append(
                {
                    "phase": phase["name"],
                    "model": model,
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                }
            )
        return response

    LLMClient.query = query


def _track_phases(phase: dict[str, str]) -> None:
    """Label each model call with the v1 step that made it."""
    from agent.address_extractor import AddressExtractor  # v1
    from agent.brand_image_detector import BrandImageDetector  # v1
    from agent.mcc_classifier import MCCClassifier  # v1

    steps = (
        (BrandImageDetector, "detect_brand_image", "brand"),
        (MCCClassifier, "classify_mcc", "mcc"),
        (AddressExtractor, "extract_address", "address"),
    )
    for cls, method, name in steps:
        original = getattr(cls, method)

        def wrapped(
            self: Any, *args: Any, _original: Any = original, _name: str = name, **kwargs: Any
        ) -> Any:
            phase["name"] = _name
            try:
                return _original(self, *args, **kwargs)
            finally:
                phase["name"] = "other"

        setattr(cls, method, wrapped)


def _use_model(model: str) -> None:
    """Point every v1 agent at another Gemini model, for when v1's configured one is retired."""
    from utils import config as v1_config  # v1
    from utils.llm import LLMClient  # v1

    v1_config.get_config().config_data["agent"]["classifier-agent"]["model"] = model
    original_detect = LLMClient._detect_provider

    def detect(self: Any, name: str) -> str:
        return "google" if name.lower().startswith("gemini") else original_detect(self, name)

    LLMClient._detect_provider = detect


def _current_url(extractor: Any) -> str | None:
    try:
        return str(extractor.driver.current_url)
    except Exception:  # noqa: BLE001 - the browser may already be gone
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1", type=Path, required=True, help="the v1 repository")
    parser.add_argument("--gold", type=Path, required=True, help="the gold-set TOML file")
    parser.add_argument("--out", type=Path, required=True, help="where to write the raw output")
    parser.add_argument("--model", help="a Gemini model to use instead of v1's configured one")
    parser.add_argument("--limit", type=int, help="run only the first N sites")
    args = parser.parse_args()

    with args.gold.resolve().open("rb") as file:
        urls = [site["url"] for site in tomllib.load(file).get("site", [])]
    urls = urls[: args.limit] if args.limit else urls
    out_path = args.out.resolve()

    v1 = args.v1.resolve()
    os.chdir(v1)  # v1 reads config.yaml and data/ by relative path
    sys.path.insert(0, str(v1))

    calls: list[dict[str, Any]] = []
    phase = {"name": "other"}
    _count_model_calls(calls, phase)
    if args.model:
        _use_model(args.model)
    _track_phases(phase)

    from agent.information_extractor import WebsiteInformationExtractor  # v1

    extractor = WebsiteInformationExtractor()
    extractor.rate_limit_delay = 0  # v1 otherwise sleeps after every site
    if not extractor.setup_driver():
        sys.exit("v1 couldn't start Chrome")
    work_dir = Path(
        tempfile.mkdtemp(prefix="v1-baseline-")
    )  # keeps v1's page copies out of the repo
    extractor.base_data_dir = str(work_dir)

    try:
        with out_path.open("w", encoding="utf-8") as out:
            for number, url in enumerate(urls, start=1):
                print(f"\n[{number}/{len(urls)}] {url}", flush=True)
                calls.clear()
                started = time.monotonic()
                error = None
                try:
                    v1_result = extractor.extract_website_information(url)
                except Exception as exc:  # noqa: BLE001 - v1 can fail in ways it doesn't catch
                    v1_result, error = {}, f"{type(exc).__name__}: {exc}"
                record = {
                    "url": url,
                    "final_url": _current_url(extractor),
                    "analyzed_at": datetime.now(UTC).isoformat(),
                    "seconds": round(time.monotonic() - started, 2),
                    "model_calls": list(calls),
                    "error": error,
                    "v1": v1_result,
                }
                out.write(json.dumps(record, default=str) + "\n")
                out.flush()
    finally:
        extractor.driver.quit()
    print(f"\nWrote {len(urls)} results to {out_path}. v1's page copies are in {work_dir}.")


if __name__ == "__main__":
    main()
