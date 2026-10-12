"""Tests for bi2.core.netsafety."""

import pytest

from bi2.core.netsafety import is_public_address


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses(address: str) -> None:
    assert is_public_address(address)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # this machine
        "10.1.2.3",  # private network
        "192.168.0.10",  # home router range
        "172.16.5.4",  # private network
        "169.254.169.254",  # cloud metadata service
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",
        "224.0.0.1",  # multicast
        "::1",  # this machine, IPv6
        "fd00::1",  # private network, IPv6
        "::ffff:10.0.0.1",  # a private IPv4 address written as IPv6
        "not an address",
    ],
)
def test_addresses_that_are_not_public(address: str) -> None:
    assert not is_public_address(address)
