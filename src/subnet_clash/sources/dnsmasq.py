"""dnsmasq configuration: the address pools declared by ``dhcp-range=``.

Handled forms (tags, interfaces and lease times are ignored)::

    dhcp-range=192.168.0.50,192.168.0.150,12h
    dhcp-range=set:red,192.168.0.50,192.168.0.150,255.255.255.0,12h
    dhcp-range=192.168.0.0,static,255.255.255.0
    dhcp-range=fd00::2,fd00::500,64

A ``dhcp-range`` that names a single address and no netmask (``dhcp-range=10.60.0.0,static``) is
*not* a ``/32``: dnsmasq takes the prefix from the interface the range is served on, and v0.1 never
looks at interfaces. Such a line is reported as an undetermined range -- listed, warned about, and
compared with nothing -- because inventing a ``/32`` invents findings and dropping the line hides
one.

``conf-file``/``conf-dir`` includes are *not* followed: v0.1 only reads the files you name.
"""

from __future__ import annotations

import ipaddress
import re

from ..errors import InputError
from ..model import Location, Network, RangeEntry
from ..ranges import networks_from_bounds, parse_address
from ..warn import warn

_DIRECTIVE = re.compile(r"^(?:--?)?(?P<key>[a-z0-9-]+)\s*=\s*(?P<value>.*)$", re.IGNORECASE)
_TAGGED = re.compile(r"^(set|tag|interface):", re.IGNORECASE)

NO_NETMASK = (
    "dhcp-range names one address and no netmask, so its size comes from the interface; "
    "reported as an undetermined range instead of being guessed at"
)


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


def _parse_dhcp_range(value: str, where: str) -> tuple[str, tuple[Network, ...], str | None]:
    """``(text for the report, networks, reason the extent is unknown)``."""
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
        return f"{start}-{end}", networks_from_bounds(start, end, where), None
    single = ips[0][1]
    if mask is not None:
        try:
            network = ipaddress.ip_network(f"{single}/{mask}", strict=False)
        except ValueError as exc:
            raise InputError(f"bad dhcp-range netmask {mask!r} ({exc})", where) from exc
        return f"{single}/{mask}", (network,), None
    parse_address(single, where)  # still has to be an address, whatever its prefix turns out to be
    warn(NO_NETMASK, where)
    return single, (), NO_NETMASK


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
        label, networks, undetermined = _parse_dhcp_range(matched.group("value").strip(), where)
        entries.append(
            RangeEntry(
                source="dnsmasq",
                role="dnsmasq-range",
                name="dnsmasq dhcp-range",
                raw=label,
                networks=networks,
                location=Location(filename, lineno, "dhcp-range"),
                scope=f"{filename}#line{lineno}",
                undetermined=undetermined,
            )
        )
    return entries
