"""Small builders for test data, so tests only spell out what they care about."""

from datetime import UTC, datetime
from typing import Any

from bi2.core.models import SiteResult

NOT_FOUND: dict[str, Any] = {"status": "not_found"}


def answered(value: Any, *, confidence: float = 0.9, status: str = "ok") -> dict[str, Any]:
    """A field that was answered, as the dict a SiteResult is built from."""
    return {"value": value, "status": status, "confidence": confidence, "source": "test"}


def site_result(url: str = "https://example-cafe.ca/", **fields: Any) -> SiteResult:
    """A SiteResult where every field is not found unless given."""
    data: dict[str, Any] = {
        "page": {"url": url, "final_url": url, "kind": "own_website"},
        "analyzed_at": datetime(2026, 10, 11, tzinfo=UTC),
        "seconds": 10.0,
        "company_name": NOT_FOUND,
        "logo": NOT_FOUND,
        "mcc": NOT_FOUND,
        "address": NOT_FOUND,
        "versions": {"pipeline": "test"},
    }
    data.update(fields)
    return SiteResult.model_validate(data)
