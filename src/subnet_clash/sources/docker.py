"""Saved ``docker network inspect`` JSON (a file or ``-`` for stdin).

Findings point at a JSON key path such as ``$[0].IPAM.Config[0].Subnet`` and, because JSON values
carry no position, at the line where that value literally appears in the file. The line is found by
walking occurrences of the value in document order, which matches the order we extract them in.
"""

from __future__ import annotations

import json
from typing import Any

from ..errors import InputError
from ..model import Location, RangeEntry
from ..ranges import parse_network


class _LineFinder:
    """Maps an extracted value to the line it sits on, honouring repeated values."""

    def __init__(self, text: str) -> None:
        self._lines = text.splitlines()
        self._cursor: dict[str, int] = {}

    def line_for(self, value: str) -> int | None:
        needle = f'"{value}"'
        start = self._cursor.get(value, 0)
        for offset in range(start, len(self._lines)):
            if needle in self._lines[offset]:
                self._cursor[value] = offset + 1
                return offset + 1
        return None


def _networks_of(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    raise InputError("expected a JSON array of networks or a single network object")


def read(text: str, filename: str) -> list[RangeEntry]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON ({exc.msg})", f"{filename}:{exc.lineno}") from exc

    finder = _LineFinder(text)
    top_level_list = isinstance(payload, list)
    entries: list[RangeEntry] = []

    for index, network in enumerate(_networks_of(payload)):
        prefix = f"$[{index}]" if top_level_list else "$"
        net_name = network.get("Name") or network.get("Id") or f"network #{index}"
        ipam = network.get("IPAM")
        if not isinstance(ipam, dict):
            continue
        configs = ipam.get("Config")
        if configs is None:
            continue
        if not isinstance(configs, list):
            raise InputError(f"{prefix}.IPAM.Config is not a list", filename)
        for config_index, config in enumerate(configs):
            if not isinstance(config, dict):
                continue
            for field in ("Subnet", "IPRange"):
                value = config.get(field)
                if not value:
                    continue
                if not isinstance(value, str):
                    raise InputError(
                        f"{prefix}.IPAM.Config[{config_index}].{field} is not a string", filename
                    )
                key = f"{prefix}.IPAM.Config[{config_index}].{field}"
                line = finder.line_for(value)
                where = f"{filename}:{line}" if line else f"{filename} ({key})"
                entries.append(
                    RangeEntry(
                        source="docker",
                        role="docker-subnet" if field == "Subnet" else "docker-iprange",
                        name=f'docker network "{net_name}" {field}',
                        raw=value,
                        networks=(parse_network(value, where),),
                        location=Location(filename, line, key),
                        scope=f"{filename}#{net_name}",
                    )
                )
    return entries
