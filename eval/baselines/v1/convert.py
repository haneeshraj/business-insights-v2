"""Turn run_v1.py's raw output into SiteResult lines that `bi2 eval score` can read.

Prices are US dollars per million tokens for the model v1 used. Look them up on the
provider's pricing page when you run this, since they change. Without prices, tokens are still
counted but the cost shows as not recorded.
"""

import argparse
import csv
import json
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from bi2.core.models import (
    Address,
    AddressResult,
    Coordinates,
    Cost,
    Logo,
    LogoResult,
    Mcc,
    MccResult,
    NameResult,
    PageInfo,
    PageKind,
    PhoneResult,
    SiteResult,
    SocialResult,
    Status,
    StepOutcome,
    StepRecord,
    Versions,
)

_CONFIDENCE_WORDS = {"high": 0.8, "medium": 0.6, "low": 0.4}


def _mcc_descriptions() -> dict[str, str]:
    text = files("bi2.data").joinpath("mcc_codes.csv").read_text(encoding="utf-8")
    return {row["MCC"]: row["Description"] for row in csv.DictReader(text.splitlines())}


def _confidence(value: Any) -> float:
    if isinstance(value, str):
        return _CONFIDENCE_WORDS.get(value.lower(), 0.5)
    if isinstance(value, int | float):
        return min(max(float(value), 0.0), 1.0)
    return 0.5


def _cost(calls: list[dict[str, Any]], phases: set[str], prices: tuple[Decimal, Decimal]) -> Cost:
    picked = [call for call in calls if call["phase"] in phases]
    tokens_in = sum(int(call["input_tokens"]) for call in picked)
    tokens_out = sum(int(call["output_tokens"]) for call in picked)
    usd = (tokens_in * prices[0] + tokens_out * prices[1]) / Decimal(1_000_000)
    return Cost(usd=usd, input_tokens=tokens_in, output_tokens=tokens_out, model_calls=len(picked))


def _steps(name: str, cost: Cost, outcome: StepOutcome, detail: str = "") -> tuple[StepRecord, ...]:
    if not cost.model_calls and not detail:
        return ()
    return (StepRecord(step=name, outcome=outcome, detail=detail, cost=cost),)


def _web_url(value: Any) -> str | None:
    text = str(value or "")
    return text if text.startswith(("http://", "https://")) else None


def _coordinates(v1: dict[str, Any]) -> Coordinates | None:
    geocoding = (v1.get("address_extraction") or {}).get("geocoding") or {}
    try:
        return Coordinates(latitude=float(geocoding["lat"]), longitude=float(geocoding["lon"]))
    except (KeyError, TypeError, ValueError):
        return None


def _failed_site(raw: dict[str, Any], message: str) -> SiteResult:
    failed = {
        "status": Status.ERROR,
        "steps": (StepRecord(step="v1", outcome=StepOutcome.FAILED, detail=message),),
    }
    return SiteResult(
        page=PageInfo(url=raw["url"]),
        analyzed_at=raw["analyzed_at"],
        seconds=raw["seconds"],
        company_name=NameResult.model_validate(failed),
        logo=LogoResult.model_validate(failed),
        mcc=MccResult.model_validate(failed),
        address=AddressResult.model_validate(failed),
        phone=PhoneResult.model_validate(failed),
        social_links=SocialResult.model_validate(failed),
        error=message,
        versions=Versions(pipeline="v1"),
    )


def convert(
    raw: dict[str, Any], prices: tuple[Decimal, Decimal], descriptions: dict[str, str]
) -> SiteResult:
    """Build a SiteResult from one line of run_v1.py output."""
    v1 = raw.get("v1") or {}
    if raw.get("error") or v1.get("status") != "success":
        return _failed_site(raw, raw.get("error") or v1.get("error") or "v1 failed")
    calls = raw.get("model_calls", [])

    name = str(v1.get("company_name") or "").strip()
    name_cost = _cost(calls, {"other"}, prices)
    if name:
        company_name = NameResult(
            value=name,
            status=Status.OK,
            confidence=_confidence(v1.get("company_name_confidence")),
            source=f"v1: {v1.get('company_name_source') or 'brand detection'}",
            steps=_steps("v1 other calls", name_cost, StepOutcome.RESOLVED),
        )
    else:
        company_name = NameResult(
            status=Status.NOT_FOUND,
            steps=_steps("v1 other calls", name_cost, StepOutcome.ESCALATED),
        )

    detection = v1.get("brand_image_detection") or {}
    brand_cost = _cost(calls, {"brand"}, prices)
    image = (
        (detection.get("selected_image") or {}).get("src")
        if detection.get("brand_image_found")
        else None
    )
    logo_url = _web_url(image)
    try:
        logo = LogoResult(
            value=Logo(url=logo_url),
            status=Status.OK,
            confidence=_confidence(detection.get("confidence")),
            source="v1: brand image detection",
            steps=_steps("v1 brand call", brand_cost, StepOutcome.RESOLVED),
        )
    except ValidationError:
        detail = "v1 returned an unusable image URL" if image else ""
        logo = LogoResult(
            status=Status.NOT_FOUND,
            steps=_steps("v1 brand call", brand_cost, StepOutcome.ESCALATED, detail),
        )

    mcc_cost = _cost(calls, {"mcc"}, prices)
    code = v1.get("final_mcc_code")
    if code not in (None, ""):
        code_text = f"{int(str(code)):04d}"
        description = (v1.get("mcc_classification") or {}).get(
            "final_mcc_description"
        ) or descriptions.get(code_text, "unknown")
        mcc = MccResult(
            value=Mcc(code=code_text, description=description),
            status=Status.OK,
            confidence=_confidence(v1.get("mcc_confidence")),
            source="v1: two-stage classification",
            steps=_steps("v1 mcc calls", mcc_cost, StepOutcome.RESOLVED),
        )
    else:
        mcc = MccResult(
            status=Status.NOT_FOUND, steps=_steps("v1 mcc calls", mcc_cost, StepOutcome.ESCALATED)
        )

    address_cost = _cost(calls, {"address"}, prices)
    text = str(v1.get("final_address") or "").strip()
    if text:
        address = AddressResult(
            value=Address(text=text, coordinates=_coordinates(v1)),
            status=Status.OK,
            confidence=_confidence(v1.get("address_confidence")),
            source=f"v1: {v1.get('address_source') or 'address extraction'}",
            steps=_steps("v1 address search", address_cost, StepOutcome.RESOLVED),
        )
    else:
        address = AddressResult(
            status=Status.NOT_FOUND,
            steps=_steps("v1 address search", address_cost, StepOutcome.ESCALATED),
        )

    return SiteResult(
        page=PageInfo(
            url=raw["url"], final_url=_web_url(raw.get("final_url")), kind=PageKind.OWN_WEBSITE
        ),
        analyzed_at=raw["analyzed_at"],
        seconds=raw["seconds"],
        company_name=company_name,
        logo=logo,
        mcc=mcc,
        address=address,
        # v1 doesn't look for phone numbers or social links.
        phone=PhoneResult(status=Status.NOT_FOUND),
        social_links=SocialResult(status=Status.NOT_FOUND),
        versions=Versions(pipeline="v1"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path, help="run_v1.py's output")
    parser.add_argument("out", type=Path, help="where to write the SiteResult lines")
    parser.add_argument(
        "--input-price", type=Decimal, default=Decimal(0), help="USD per million input tokens"
    )
    parser.add_argument(
        "--output-price", type=Decimal, default=Decimal(0), help="USD per million output tokens"
    )
    args = parser.parse_args()

    prices = (args.input_price, args.output_price)
    descriptions = _mcc_descriptions()
    lines = [line for line in args.raw.read_text(encoding="utf-8").splitlines() if line.strip()]
    with args.out.open("w", encoding="utf-8") as out:
        for line in lines:
            out.write(convert(json.loads(line), prices, descriptions).model_dump_json() + "\n")
    print(f"Converted {len(lines)} results into {args.out}")


if __name__ == "__main__":
    main()
