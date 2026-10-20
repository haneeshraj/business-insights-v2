"""Tests for results as CSV, and site lists in files."""

import csv
import io
from pathlib import Path

from bi2.cli.analyze import urls_in_file
from bi2.cli.output import results_csv
from tests.factories import answered, site_result


def test_each_field_has_four_columns() -> None:
    result = site_result(
        company_name=answered("Example Cafe"),
        mcc=answered({"code": "5814", "description": "Fast Food Restaurants"}),
        address=answered(
            {
                "text": "1 Queen St W, Toronto",
                "coordinates": {"latitude": 43.65, "longitude": -79.38},
            },
            status="needs_review",
            confidence=0.7,
        ),
    )
    rows = list(csv.DictReader(io.StringIO(results_csv([result]))))
    row = rows[0]
    assert (row["company_name"], row["company_name_status"], row["company_name_confidence"]) == (
        "Example Cafe",
        "ok",
        "0.90",
    )
    assert row["mcc"] == "5814 Fast Food Restaurants"
    assert row["address"] == "1 Queen St W, Toronto (43.65000, -79.38000)"
    assert row["address_status"] == "needs_review"
    assert row["logo"] == ""


def test_a_site_list_leaves_out_blank_and_comment_lines(tmp_path: Path) -> None:
    path = tmp_path / "sites.txt"
    path.write_text("# cafes\nhttps://example-cafe.ca/\n\n  example-bakery.ca \n", encoding="utf-8")
    assert urls_in_file(path) == ["https://example-cafe.ca/", "example-bakery.ca"]
