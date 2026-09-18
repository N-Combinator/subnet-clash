"""dnsmasq configuration: the address pools declared by ``dhcp-range=``.

Handled forms (tags, interfaces and lease times are ignored)::

    dhcp-range=192.168.0.50,192.168.0.150,12h
    dhcp-range=set:red,192.168.0.50,192.168.0.150,255.255.255.0,12h
    dhcp-range=192.168.0.0,static,255.255.255.0
    dhcp-range=fd00::2,fd00::500,64

``conf-file``/``conf-dir`` includes are *not* followed: v0.1 only reads the files you name.
"""

from __future__ import annotations

import ipaddress
import re

from ..errors import InputError
from ..model import Location, Network, RangeEntry
from ..ranges import networks_from_bounds, parse_address

_DIRECTIVE = re.compile(r"^(?:--?)?(?P<key>[a-z0-9-]+)\s*=\s*(?P<value>.*)$", re.IGNORECASE)
_TAGGED = re.compile(r"^(set|tag|interface):", re.IGNORECASE)


def _is_ip(token: str) -> bool:
    try:
        ipaddress.ip_address(token)
    except ValueError:
        return False
    return True


def _is_netmask(token: str) -> bool:
    try:
        address = ipaddress.IPv4Address(token)
    except ipaddress.AddressValueError:
        return False
    bits = int(address)
    # a netmask is a run of ones followed by a run of zeros
    return bits != 0 and ((bits ^ 0xFFFFFFFF) & ((bits ^ 0xFFFFFFFF) + 1)) == 0


def _parse_dhcp_range(value: str, where: str) -> tuple[str, tuple[Network, ...]]:
    tokens = [t.strip() for t in value.split(",") if t.strip()]
    tokens = [t for t in tokens if not _TAGGED.match(t)]
    ips = [(index, token) for index, token in enumerate(tokens) if _is_ip(token)]
    if not ips:
        raise InputError(f"dhcp-range without an IP address: {value!r}", where)

    mask: str | None = None
    if len(ips) >= 3 and _is_netmask(ips[2][1]):
        mask = ips[2][1]
        ips = ips[:2]
    elif len(ips) == 2 and _is_netmask(ips[1][1]) and ips[1][0] != ips[0][0] + 1:
        # e.g. "192.168.0.0,static,255.255.255.0" -- the second IP is a mask, not a range end
        mask = ips[1][1]
        ips = ips[:1]

    if len(ips) >= 2:
        start, end = ips[0][1], ips[1][1]
        return f"{start}-{end}", networks_from_bounds(start, end, where)
    single = ips[0][1]
    if mask is not None:
        try:
            network = ipaddress.ip_network(f"{single}/{mask}", strict=False)
        except ValueError as exc:
            raise InputError(f"bad dhcp-range netmask {mask!r} ({exc})", where) from exc
        return f"{single}/{mask}", (network,)
    address = parse_address(single, where)
    return single, (ipaddress.ip_network(f"{address}/{address.max_prefixlen}"),)


def read(text: str, filename: str) -> list[RangeEntry]:
    entries: list[RangeEntry] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        matched = _DIRECTIVE.match(line)
        if matched is None or matched.group("key").lower() != "dhcp-range":
            continue
        where = f"{filename}:{lineno}"
        label, networks = _parse_dhcp_range(matched.group("value").strip(), where)
        entries.append(
            RangeEntry(
                source="dnsmasq",
                role="dnsmasq-range",
                name="dnsmasq dhcp-range",
                raw=label,
                networks=networks,
                location=Location(filename, lineno, "dhcp-range"),
                scope=f"{filename}#line{lineno}",
            )
        )
    return entries
