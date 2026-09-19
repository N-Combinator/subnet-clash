"""dnsmasq configuration: the address pools declared by ``dhcp-range=``.

The fields are read in the order dnsmasq documents them,
``<start-addr>[,<end-addr>|<mode>][,<netmask>[,<broadcast>]][,<lease time>]``, so every spelling
of the directive lands in the right slot (tags, modes, broadcasts and lease times are ignored)::

    dhcp-range=192.168.0.50,192.168.0.150,12h
    dhcp-range=set:red,192.168.0.50,192.168.0.150,255.255.255.0,12h
    dhcp-range=192.168.0.0,static,255.255.255.0
    dhcp-range=192.168.0.0,static,255.255.255.0,192.168.0.255
    dhcp-range=192.168.0.50,192.168.0.150,255.255.255.0,192.168.0.255,12h
    dhcp-range=fd00::2,fd00::500,64

A ``dhcp-range`` that names a single address and no netmask (``dhcp-range=10.60.0.0,static``) is
*not* a ``/32``: dnsmasq takes the prefix from the interface the range is served on, and v0.1 never
looks at interfaces. Such a line is reported as an undetermined range -- listed, warned about, and
compared with nothing -- because inventing a ``/32`` invents findings and dropping the line hides
one.

Comments are cut at the first unquoted ``#`` anywhere on the line, which is what dnsmasq's own
config reader does -- ``dhcp-range=10.70.0.0,static,255.255.255.0 # tftp clients`` is the same
directive with or without the note on the right.

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

# The keywords dnsmasq accepts where an end address could stand (man dnsmasq, --dhcp-range).
# One of these in that slot means the directive states no end address at all.
_MODES = frozenset(
    {
        "static",
        "proxy",
        "ra-only",
        "ra-names",
        "ra-stateless",
        "ra-advrouter",
        "slaac",
        "off",
        "bootp",
    }
)
_MODE_PREFIXES = ("constructor:", "constructor-noauth:")

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


def _is_mode(token: str) -> bool:
    lowered = token.lower()
    return lowered in _MODES or lowered.startswith(_MODE_PREFIXES)


def _parse_dhcp_range(value: str, where: str) -> tuple[str, tuple[Network, ...], str | None]:
    """``(text for the report, networks, reason the extent is unknown)``.

    The slots are filled in dnsmasq's own field order rather than by counting IP-looking tokens:
    a fixed position gets the netmask wrong as soon as the line carries a broadcast address
    (``192.168.0.0,static,255.255.255.0,192.168.0.255``), and the start address then pairs with
    the netmask as if it were the end of the pool.
    """
    tokens = [t.strip() for t in value.split(",") if t.strip()]
    tokens = [t for t in tokens if not _TAGGED.match(t)]
    ips = [(index, token) for index, token in enumerate(tokens) if _is_ip(token)]
    if not ips:
        raise InputError(f"dhcp-range without an IP address: {value!r}", where)

    start_index, single = ips[0]
    rest = ips[1:]

    end: str | None = None
    if rest:
        index, token = rest[0]
        between = tokens[start_index + 1 : index]
        if any(_is_mode(word) for word in between):
            pass  # a mode keyword stands where the end address would: the line states no end
        elif between and _is_netmask(token):
            pass  # an unknown word in the mode slot; a netmask behind it is still a netmask
        else:
            end, rest = token, rest[1:]

    mask: str | None = None
    if rest and _is_netmask(rest[0][1]):
        # any IP token after the netmask is the broadcast address, which says nothing about the
        # extent of the pool, so nothing past this point is read
        mask = rest[0][1]

    if end is not None:
        return f"{single}-{end}", networks_from_bounds(single, end, where), None
    if mask is not None:
        try:
            network = ipaddress.ip_network(f"{single}/{mask}", strict=False)
        except ValueError as exc:
            raise InputError(f"bad dhcp-range netmask {mask!r} ({exc})", where) from exc
        return f"{single}/{mask}", (network,), None
    parse_address(single, where)  # still has to be an address, whatever its prefix turns out to be
    warn(NO_NETMASK, where)
    return single, (), NO_NETMASK


def _strip_comment(line: str) -> str:
    """Cut a trailing comment the way dnsmasq's config reader does: at the first unquoted ``#``.

    Honouring only a ``#`` in column one leaves the comment glued to the last value, where it
    quietly stops being what it was: ``,255.255.255.0 # tftp clients`` is not a netmask and
    ``,10.70.0.200 # spare`` is not an address, so a determined pool turns into an undetermined
    one -- a wrong answer rather than a loud one.

    Quotes are read only to find that ``#``. dnsmasq removes them from the value; we leave the
    text as it is, because no range spelling we read uses them.
    """
    quoted = False
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == "#" and not quoted:
            return line[:index]
    return line


def read(text: str, filename: str) -> list[RangeEntry]:
    entries: list[RangeEntry] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw).strip()
        if not line:
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
