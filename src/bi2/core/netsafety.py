"""Which IP addresses v2 may fetch from. Pure: the DNS lookup itself happens in fetch/."""

import ipaddress


def is_public_address(address: str) -> bool:
    """Whether an IP address is on the public internet.

    Private, loopback, link-local (including cloud metadata at 169.254.169.254), reserved and
    multicast addresses are not, and neither is anything that isn't an IP address.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast
