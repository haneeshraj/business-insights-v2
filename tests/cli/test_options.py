"""Tests for the options several commands share."""

from bi2.cli.options import default_concurrency


def test_sites_loaded_at_once_follow_the_machines_cores() -> None:
    assert default_concurrency(20) == 8  # the fastest measured, on a 20-core laptop
    assert default_concurrency(32) == 8  # more sites at once than that only slowed each down
    assert default_concurrency(8) == 4
    assert default_concurrency(2) == 2
    assert default_concurrency(None) == 2  # when the core count can't be told
