"""Set algebra over lists of IP networks. Nothing here touches the network or the filesystem."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Sequence

from .errors import InputError
from .model import Network

DEFAULT_ROUTES = (
    ipaddress.ip_network("0.0.0.0/0"),
    ipaddress.ip_network("::/0"),
)


def parse_network(text: str, location: str | None = None) -> Network:
    """Parse ``10.0.0.1/24`` or a bare address into the network it designates.

    Host bits are allowed and dropped: an interface address ``10.0.0.1/24`` describes the whole
    ``10.0.0.0/24`` on-link prefix, which is exactly the range that can clash with something else.
    """
    value = text.strip()
    if not value:
        raise InputError("empty IP range", location)
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise InputError(f"not an IP network: {text!r} ({exc})", location) from exc


Address = ipaddress.IPv4Address | ipaddress.IPv6Address


def parse_address(text: str, location: str | None = None) -> Address:
    try:
        return ipaddress.ip_address(text.strip())
    except ValueError as exc:
        raise InputError(f"not an IP address: {text!r} ({exc})", location) from exc


def networks_from_bounds(start: str, end: str, location: str | None = None) -> tuple[Network, ...]:
    """Turn an inclusive ``start``-``end`` address range (dnsmasq style) into networks."""
    first = parse_address(start, location)
    last = parse_address(end, location)
    if first.version != last.version:
        raise InputError(f"mixed IPv4/IPv6 range {start}-{end}", location)
    if int(last) < int(first):
        raise InputError(f"range end {end} is below its start {start}", location)
    return tuple(ipaddress.summarize_address_range(first, last))


def is_default_route(network: Network) -> bool:
    return network in DEFAULT_ROUTES


def collapse(networks: Iterable[Network]) -> tuple[Network, ...]:
    """Collapse to a minimal, sorted set of networks (v4 and v6 handled separately)."""
    out: list[Network] = []
    for version in (4, 6):
        same = [n for n in networks if n.version == version]
        if same:
            out.extend(ipaddress.collapse_addresses(same))  # type: ignore[arg-type]
    return tuple(out)


def _covers(outer: Network, inner: Network) -> bool:
    return outer.version == inner.version and inner.subnet_of(outer)  # type: ignore[arg-type]


def overlaps(a: Network, b: Network) -> bool:
    """Two IP networks intersect only by containment, so this is just a two-way subnet test."""
    return _covers(a, b) or _covers(b, a)


def subtract(left: Sequence[Network], right: Sequence[Network]) -> tuple[Network, ...]:
    """Everything in ``left`` that is not covered by ``right``."""
    remaining = list(collapse(left))
    for cut in right:
        nxt: list[Network] = []
        for net in remaining:
            if _covers(cut, net):
                continue  # fully removed
            if _covers(net, cut):
                nxt.extend(net.address_exclude(cut))  # type: ignore[arg-type]
            else:
                nxt.append(net)
        remaining = nxt
        if not remaining:
            break
    return collapse(remaining)


def intersect(left: Sequence[Network], right: Sequence[Network]) -> tuple[Network, ...]:
    """The addresses present in both lists, as a collapsed set of networks."""
    shared: list[Network] = []
    for a in left:
        for b in right:
            if _covers(a, b):
                shared.append(b)
            elif _covers(b, a):
                shared.append(a)
    return collapse(shared)


Relation = tuple[str | None, tuple[Network, ...], str | None]


def relation(left: Sequence[Network], right: Sequence[Network]) -> Relation:
    """Classify how two address sets relate.

    Returns ``(kind, intersection, container)`` where ``kind`` is:

    * ``None``      - disjoint, nothing to report
    * ``identical`` - the two sets cover exactly the same addresses
    * ``contains``  - one set is fully inside the other (``container`` is ``"left"``/``"right"``)
    * ``overlap``   - they share addresses but each also has addresses the other lacks
    """
    shared = intersect(left, right)
    if not shared:
        return None, (), None
    left_only = subtract(left, right)
    right_only = subtract(right, left)
    if not left_only and not right_only:
        return "identical", shared, None
    if not left_only:
        return "contains", shared, "right"
    if not right_only:
        return "contains", shared, "left"
    return "overlap", shared, None
