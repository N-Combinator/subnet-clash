"""The data the whole tool passes around: where a range came from, and what it covers."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True)
class Location:
    """Where a range literally sits: a file plus a line and/or a structured key."""

    file: str
    line: int | None = None
    key: str | None = None

    def __str__(self) -> str:
        return f"{self.file}:{self.line}" if self.line is not None else self.file

    def as_dict(self) -> dict[str, object]:
        return {"file": self.file, "line": self.line, "key": self.key, "text": str(self)}


@dataclass(frozen=True)
class RangeEntry:
    """One address range read out of one source file.

    ``scope`` is the logical configuration unit the range belongs to (one docker network, one
    WireGuard peer, one netplan device...). Ranges sharing a scope are never compared against each
    other: a docker ``IPRange`` sitting inside its own ``Subnet`` is the design, not a clash.

    ``undetermined`` holds the reason a line declares a range whose extent the file does not state
    (a dnsmasq ``dhcp-range`` whose netmask comes from the interface). Such an entry carries no
    ``networks`` and is never compared: guessing a prefix would invent a finding, and dropping the
    line would hide one.
    """

    source: str
    role: str
    name: str
    raw: str
    networks: tuple[Network, ...]
    location: Location
    scope: str = ""
    undetermined: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "role": self.role,
            "name": self.name,
            "range": self.raw,
            "networks": [str(n) for n in self.networks],
            "location": str(self.location),
            "file": self.location.file,
            "line": self.location.line,
            "key": self.location.key,
            "undetermined": self.undetermined,
        }


@dataclass(frozen=True)
class Clash:
    """Two ranges from two different scopes that share addresses."""

    kind: str  # "identical" | "contains" | "overlap"
    a: RangeEntry
    b: RangeEntry
    intersection: tuple[Network, ...]
    #: for ``contains``: which side is the outer one ("a" or "b"); ``None`` otherwise
    container: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "container": self.container,
            "intersection": [str(n) for n in self.intersection],
            "a": self.a.as_dict(),
            "b": self.b.as_dict(),
        }


@dataclass(frozen=True)
class DefaultRangeWarning:
    """A configured range touches a documented, widely used default range."""

    entry: RangeEntry
    default_name: str
    default_network: Network
    default_kind: str
    default_source: str
    relation: str

    def as_dict(self) -> dict[str, object]:
        return {
            "relation": self.relation,
            "default": {
                "name": self.default_name,
                "network": str(self.default_network),
                "kind": self.default_kind,
                "source": self.default_source,
            },
            "entry": self.entry.as_dict(),
        }


@dataclass
class Report:
    entries: list[RangeEntry] = field(default_factory=list)
    clashes: list[Clash] = field(default_factory=list)
    warnings: list[DefaultRangeWarning] = field(default_factory=list)
    skipped_default_routes: list[RangeEntry] = field(default_factory=list)
    undetermined: list[RangeEntry] = field(default_factory=list)
