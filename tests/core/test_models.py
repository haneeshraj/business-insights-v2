"""Tests for the shared data types in bi2.core.models."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from bi2.core.models import (
    FIELD_NAMES,
    Cost,
    Evidence,
    FieldResult,
    Logo,
    LogoCandidate,
    Mcc,
    PageInfo,
    PageKind,
    SiteResult,
    Status,
    StepOutcome,
    StepRecord,
)

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _site_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "page": {
            "url": "https://example-cafe.ca/",
            "final_url": "https://example-cafe.ca/",
            "kind": "own_website",
        },
        "analyzed_at": NOW,
        "seconds": 12.5,
        "company_name": {
            "value": "Example Cafe",
            "status": "ok",
            "confidence": 0.95,
            "source": "structured data + page title",
        },
        "logo": {
            "value": {"url": "https://example-cafe.ca/logo.png"},
            "status": "ok",
            "confidence": 0.9,
            "source": "structured data",
        },
        "mcc": {
            "value": {"code": "5814", "description": "Fast Food Restaurants"},
            "status": "needs_review",
            "confidence": 0.6,
            "source": "decider",
            "steps": [
                {
                    "step": "decider",
                    "outcome": "escalated",
                    "detail": "close runner-up",
                    "confidence": 0.6,
                    "cost": {"usd": "0.0004", "input_tokens": 900, "model_calls": 1},
                }
            ],
        },
        "address": {"status": "not_found"},
        "versions": {"pipeline": "2.0.0.dev0"},
    }
    data.update(overrides)
    return data


def test_an_answered_field_needs_a_value_confidence_and_source() -> None:
    with pytest.raises(ValidationError, match="needs a value, a confidence and a source"):
        FieldResult[str](value="Example Cafe", status=Status.OK, confidence=0.9)


def test_needs_review_keeps_the_best_guess() -> None:
    field = FieldResult[str](
        value="Example Cafe", status=Status.NEEDS_REVIEW, confidence=0.55, source="llm"
    )
    assert field.value == "Example Cafe"


@pytest.mark.parametrize("status", [Status.NOT_FOUND, Status.ERROR])
def test_not_found_and_error_never_carry_a_guess(status: Status) -> None:
    with pytest.raises(ValidationError, match="not even a guess"):
        FieldResult[str](value="Example Cafe", status=status, confidence=0.3, source="llm")


def test_a_fields_cost_is_the_sum_of_its_steps() -> None:
    spent = Cost(usd=Decimal("0.002"), input_tokens=1200, output_tokens=40, model_calls=1)
    step = StepRecord(step="llm", outcome=StepOutcome.RESOLVED, confidence=0.9, cost=spent)
    field = FieldResult[str](
        value="Example Cafe", status=Status.OK, confidence=0.9, source="llm", steps=(step, step)
    )
    assert field.cost == Cost(
        usd=Decimal("0.004"), input_tokens=2400, output_tokens=80, model_calls=2
    )


def test_mcc_codes_keep_leading_zeros_and_must_be_four_digits() -> None:
    assert Mcc(code="0742", description="Veterinary Services").code == "0742"
    with pytest.raises(ValidationError, match="should match pattern"):
        Mcc(code="742", description="Veterinary Services")


def test_logo_rejects_placeholder_data_urls() -> None:
    # Lazy-loading pages put a blank placeholder where the real image URL should be.
    placeholder = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="
    with pytest.raises(ValidationError, match="http or https URL"):
        Logo(url=placeholder)


def test_platform_profiles_name_their_platform() -> None:
    profile = PageInfo(
        url="https://www.pinterest.com/examplecafe/",
        kind=PageKind.PLATFORM_PROFILE,
        platform="pinterest",
        own_website="https://example-cafe.ca/",
    )
    assert profile.platform == "pinterest"
    with pytest.raises(ValidationError, match="needs the platform's name"):
        PageInfo(url="https://www.pinterest.com/examplecafe/", kind=PageKind.PLATFORM_PROFILE)


def test_own_websites_have_no_platform() -> None:
    with pytest.raises(ValidationError, match="only platform profiles"):
        PageInfo(url="https://example-cafe.ca/", kind=PageKind.OWN_WEBSITE, platform="pinterest")


def test_logo_candidate_numbers_are_unique() -> None:
    page = PageInfo(url="https://example-cafe.ca/", kind=PageKind.OWN_WEBSITE)
    candidates = (
        LogoCandidate(number=1, kind="img", url="https://example-cafe.ca/a.png"),
        LogoCandidate(number=1, kind="svg"),
    )
    with pytest.raises(ValidationError, match="must be unique"):
        Evidence(page=page, logo_candidates=candidates)


def test_site_result_round_trips_through_json() -> None:
    result = SiteResult.model_validate(_site_data())
    restored = SiteResult.model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.schema_version == "2.0"
    assert isinstance(restored.logo.value, Logo)


def test_site_cost_adds_up_every_field() -> None:
    result = SiteResult.model_validate(_site_data())
    assert result.cost == Cost(usd=Decimal("0.0004"), input_tokens=900, model_calls=1)


def test_a_failed_site_marks_every_field_as_an_error() -> None:
    failed = {"status": "error", "steps": [{"step": "fetch", "outcome": "failed"}]}
    fields = dict.fromkeys(FIELD_NAMES, failed)
    result = SiteResult.model_validate(_site_data(error="page timed out", **fields))
    assert result.error == "page timed out"
    with pytest.raises(ValidationError, match="every field must be an error"):
        SiteResult.model_validate(_site_data(error="page timed out"))


def test_unknown_keys_are_rejected_instead_of_silently_ignored() -> None:
    data = _site_data(address={"status": "not_found", "geocoding_result": {}})
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SiteResult.model_validate(data)


def test_results_are_immutable() -> None:
    result = SiteResult.model_validate(_site_data())
    with pytest.raises(ValidationError, match="frozen"):
        result.seconds = 0  # type: ignore[misc]


def test_analyzed_at_must_include_a_timezone() -> None:
    naive = datetime(2026, 10, 11, 12, 0)  # noqa: DTZ001 - deliberately missing a timezone
    with pytest.raises(ValidationError, match="timezone"):
        SiteResult.model_validate(_site_data(analyzed_at=naive))


def test_field_names_cover_every_field_result() -> None:
    declared = [
        name
        for name, info in SiteResult.model_fields.items()
        if isinstance(info.annotation, type) and issubclass(info.annotation, FieldResult)
    ]
    assert tuple(declared) == FIELD_NAMES
