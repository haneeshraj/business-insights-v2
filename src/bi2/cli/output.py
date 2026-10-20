"""Results as CSV, for spreadsheets: one row per site, and four columns per field."""

import csv
import io
from typing import Any

from bi2.core.models import FIELD_NAMES, SiteResult


def _value(field: str, value: Any) -> str:
    """A field's value as one cell."""
    if value is None:
        return ""
    match field:
        case "logo":
            colors = " ".join(value.get("colors", []))
            where = value.get("url") or value.get("image_file") or ""
            return f"{where} {colors}".strip()
        case "mcc":
            return f"{value['code']} {value['description']}"
        case "address":
            point = value.get("coordinates")
            at = f" ({point['latitude']:.5f}, {point['longitude']:.5f})" if point else ""
            return f"{value['text']}{at}"
        case "social_links":
            return " ".join(profile["url"] for profile in value)
    return str(value)


def results_csv(results: list[SiteResult]) -> str:
    """The results as CSV: the site, the page kind, then for each field its value, status,
    confidence and source, the output contract in docs/codebase.md."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    header = ["url", "page_kind", "error"]
    for field in FIELD_NAMES:
        header += [field, f"{field}_status", f"{field}_confidence", f"{field}_source"]
    writer.writerow(header)
    for result in results:
        data = result.model_dump(mode="json")
        row = [result.page.url, result.page.kind.value, result.error or ""]
        for field in FIELD_NAMES:
            answer = data[field]
            confidence = answer["confidence"]
            row += [
                _value(field, answer["value"]),
                answer["status"],
                "" if confidence is None else f"{confidence:.2f}",
                answer["source"] or "",
            ]
        writer.writerow(row)
    return out.getvalue()
