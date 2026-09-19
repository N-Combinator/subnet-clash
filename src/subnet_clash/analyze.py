"""Compare every pair of ranges and classify how they collide."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .defaults import DEFAULT_RANGES
from .model import Clash, DefaultRangeWarning, RangeEntry, Report
from .ranges import is_default_route, relation

#: A WireGuard interface address and the peers routed through that same tunnel are supposed to
#: share a subnet, so that particular same-file pairing is not a finding. Two *peers* of the same
#: tunnel overlapping each other still is: that one breaks routing.
_EXPECTED_WIREGUARD_PAIR = {"interface-address", "peer-allowedips"}


def _is_expected_pair(a: RangeEntry, b: RangeEntry) -> bool:
    return (
        a.source == "wireguard"
        and b.source == "wireguard"
        and a.location.file == b.location.file
        and {a.role, b.role} == _EXPECTED_WIREGUARD_PAIR
    )


def _sort_key(entry: RangeEntry) -> tuple[str, int, str]:
    return (entry.location.file, entry.location.line or 0, entry.location.key or "")


def find_clashes(entries: Sequence[RangeEntry]) -> list[Clash]:
    """All pairs of ranges from *different* scopes that share at least one address."""
    ordered = sorted(entries, key=_sort_key)
    clashes: list[Clash] = []
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            if a.scope == b.scope or _is_expected_pair(a, b):
                continue
            kind, shared, container = relation(a.networks, b.networks)
            if kind is None:
                continue
            side = None if container is None else ("a" if container == "left" else "b")
            clashes.append(Clash(kind=kind, a=a, b=b, intersection=shared, container=side))
    return clashes


def find_default_range_warnings(entries: Sequence[RangeEntry]) -> list[DefaultRangeWarning]:
    """Flag ranges that land on a documented, widely deployed default range."""
    warnings: list[DefaultRangeWarning] = []
    for entry in sorted(entries, key=_sort_key):
        for default in DEFAULT_RANGES:
            kind, _shared, container = relation(entry.networks, (default.network,))
            if kind is None:
                continue
            how = ("inside" if container == "right" else "wraps") if kind == "contains" else kind
            warnings.append(
                DefaultRangeWarning(
                    entry=entry,
                    default_name=default.name,
                    default_network=default.network,
                    default_kind=default.kind,
                    default_source=default.source,
                    relation=how,
                )
            )
    return warnings


def analyze(
    entries: Iterable[RangeEntry],
    *,
    include_default_routes: bool = False,
    check_defaults: bool = True,
) -> Report:
    kept: list[RangeEntry] = []
    skipped: list[RangeEntry] = []
    undetermined: list[RangeEntry] = []
    for entry in entries:
        if entry.undetermined:
            # The file does not say how large this range is, so it cannot be compared with
            # anything; it is reported on its own instead of being guessed at.
            undetermined.append(entry)
        elif not include_default_routes and any(is_default_route(n) for n in entry.networks):
            skipped.append(entry)
        else:
            kept.append(entry)
    return Report(
        entries=kept,
        clashes=find_clashes(kept),
        warnings=find_default_range_warnings(kept) if check_defaults else [],
        skipped_default_routes=skipped,
        undetermined=undetermined,
    )
