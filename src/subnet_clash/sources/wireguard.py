"""WireGuard ``.conf`` files: ``[Interface] Address`` and ``[Peer] AllowedIPs``."""

from __future__ import annotations

import os
import re

from ..errors import InputError
from ..model import Location, RangeEntry
from ..ranges import parse_network

_SECTION = re.compile(r"^\[(?P<name>[^]]+)\]\s*$")
_KEY_VALUE = re.compile(r"^(?P<key>[A-Za-z0-9_]+)\s*=\s*(?P<value>.*)$")


def _strip_comment(line: str) -> str:
    for marker in ("#", ";"):
        idx = line.find(marker)
        if idx != -1:
            line = line[:idx]
    return line.strip()


def read(text: str, filename: str) -> list[RangeEntry]:
    interface = os.path.basename(filename)
    if interface.endswith(".conf"):
        interface = interface[: -len(".conf")]
    entries: list[RangeEntry] = []
    section = ""
    peer_index = 0
    seen_section = False

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw)
        if not line:
            continue
        matched = _SECTION.match(line)
        if matched:
            section = matched.group("name").strip().lower()
            seen_section = True
            if section == "peer":
                peer_index += 1
            continue
        pair = _KEY_VALUE.match(line)
        if pair is None:
            raise InputError(
                f"expected 'Key = value' or a [Section] header, got {line!r}",
                f"{filename}:{lineno}",
            )
        if not seen_section:
            raise InputError(
                f"key {pair.group('key')!r} appears before any [Section] header",
                f"{filename}:{lineno}",
            )
        key = pair.group("key").lower()
        value = pair.group("value").strip()
        if section == "interface" and key == "address":
            role, name, scope = (
                "interface-address",
                f"{interface} [Interface] Address",
                f"{filename}#interface",
            )
        elif section == "peer" and key == "allowedips":
            role, name, scope = (
                "peer-allowedips",
                f"{interface} [Peer #{peer_index}] AllowedIPs",
                f"{filename}#peer{peer_index}",
            )
        else:
            continue
        for token in (t.strip() for t in value.split(",")):
            if not token:
                continue
            location = Location(filename, lineno, f"[{section.capitalize()}].{pair.group('key')}")
            entries.append(
                RangeEntry(
                    source="wireguard",
                    role=role,
                    name=name,
                    raw=token,
                    networks=(parse_network(token, f"{filename}:{lineno}"),),
                    location=location,
                    scope=scope,
                )
            )
    return entries
