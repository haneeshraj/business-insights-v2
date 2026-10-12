"""Tests for the learned decision of which answers to keep without AI."""

import tomllib

from bi2.core.routing import Group, Routing

LEARNED = Routing(
    groups={
        "company_name": (
            Group(confidence=0.9, checked=6, right=3),  # often wrong, though sure
            Group(confidence=0.8, checked=10, right=10),  # always right, though unsure
            Group(confidence=0.7, checked=2, right=2),  # too few checked to count
        )
    }
)


def test_with_nothing_learned_the_accept_threshold_decides() -> None:
    assert Routing().decide("company_name", 0.9, 0.85) == (True, "")
    assert Routing().decide("company_name", 0.8, 0.85) == (
        False,
        "not sure enough: 0.80, below 0.85",
    )


def test_a_group_that_was_often_wrong_is_sent_on_however_sure() -> None:
    assert LEARNED.decide("company_name", 0.9, 0.85) == (
        False,
        "answers like this were right only 3 of 6 times",
    )


def test_a_group_that_was_always_right_is_kept_however_unsure() -> None:
    assert LEARNED.decide("company_name", 0.8, 0.85) == (
        True,
        "answers like this were right 10 of 10 times",
    )


def test_a_group_with_too_few_checks_falls_back_to_the_threshold() -> None:
    assert LEARNED.decide("company_name", 0.7, 0.85)[0] is False
    assert LEARNED.decide("phone", 0.9, 0.85) == (True, "")  # nothing learned for phones


def test_the_decision_round_trips_through_its_data_file() -> None:
    data = tomllib.loads(LEARNED.to_toml("2026-10-12"))
    assert data.pop("version") == "2026-10-12"
    assert Routing.model_validate(data) == LEARNED
