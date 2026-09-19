"""NetworkManager connection keyfiles (``*.nmconnection``).

NetworkManager stores connections in its own keyfile format -- INI, not YAML -- so the keys we
care about are ``[ipv4]/[ipv6]`` ``addressN=<cidr>[,<gateway>]`` and
``routeN=<cidr>[,<next-hop>[,<metric>]]``. It is read line by line rather than with
``configparser`` because a finding has to name the line the range sits on, and ``configparser``
does not report one.

A default route (``route1=0.0.0.0/0,...``) is read like any other range; ``analyze`` is what
sets ``0.0.0.0/0`` and ``::/0`` aside, so ``--include-default-routes`` can bring them back.
"""

from __future__ import annotations

import os
import re

from ..errors import InputError
from ..model import Location, RangeEntry
from ..ranges import parse_network

_SECTION = re.compile(r"^\[(?P<name>[^]]+)\]\s*$")
_KEY_VALUE = re.compile(r"^(?P<key>[^=]+?)\s*=\s*(?P<value>.*)$")
_ADDRESS_KEY = re.compile(r"^address(?P<index>\d+)$")
_ROUTE_KEY = re.compile(r"^route(?P<index>\d+)$")


def read(text: str, filename: str) -> list[RangeEntry]:
    connection = os.path.basename(filename)
    if connection.endswith(".nmconnection"):
        connection = connection[: -len(".nmconnection")]
    entries: list[RangeEntry] = []
    section = ""

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        matched = _SECTION.match(line)
        if matched:
            section = matched.group("name").strip().lower()
            continue
        if section not in ("ipv4", "ipv6"):
            continue
        pair = _KEY_VALUE.match(line)
        if pair is None:
            raise InputError(
                f"expected 'key=value' in [{section}], got {line!r}", f"{filename}:{lineno}"
            )
        key = pair.group("key").strip().lower()
        value = pair.group("value").split(",")[0].strip()
        if _ADDRESS_KEY.match(key):
            role, label = "nm-address", "address"
        elif _ROUTE_KEY.match(key):
            role, label = "nm-route", "route"
        else:
            continue
        if not value:
            continue
        entries.append(
            RangeEntry(
                source="networkmanager",
                role=role,
                name=f"NetworkManager {connection} [{section}] {label}",
                raw=value,
                networks=(parse_network(value, f"{filename}:{lineno}"),),
                location=Location(filename, lineno, f"[{section}].{pair.group('key').strip()}"),
                scope=f"{filename}#{section}",
            )
        )
    return entries
