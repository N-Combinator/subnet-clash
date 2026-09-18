"""Saved ``docker network inspect`` JSON (a file or ``-`` for stdin).

Findings point at a JSON key path such as ``$[0].IPAM.Config[0].Subnet`` *and* at the line that
value sits on. The line comes from the value itself: the standard library's JSON parser does the
parsing, with its string hook swapped for one that keeps each string's offset in the document. A
value is therefore reported where the parser read it, not where the same text happens to occur --
an earlier ``"Labels": {"planned-subnet": "10.8.0.0/24"}`` cannot lend its line to a later
``Subnet`` holding the same CIDR.
"""

from __future__ import annotations

import bisect
import json
import json.decoder
import json.scanner
from typing import Any

from ..errors import InputError
from ..model import Location, RangeEntry
from ..ranges import parse_network


class _PositionedStr(str):
    """A JSON string value that remembers where the parser found it."""

    offset: int

    def __new__(cls, value: str, offset: int) -> _PositionedStr:
        positioned = super().__new__(cls, value)
        positioned.offset = offset
        return positioned


def _parse_positioned_string(text: str, end: int, strict: bool = True) -> tuple[str, int]:
    """``json.decoder.scanstring``, keeping the offset of the opening quote."""
    value, next_end = json.decoder.scanstring(text, end, strict)
    return _PositionedStr(value, end - 1), next_end


class _PositionDecoder(json.JSONDecoder):
    """``json.loads`` with one thing changed: string *values* keep their offset.

    Only ``parse_string`` is replaced, so the grammar, the accepted documents and the
    ``JSONDecodeError`` messages are the standard library's, unchanged. Object *keys* are read by
    the decoder's own scanner and stay plain strings -- we only ever need to locate values.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.parse_string = _parse_positioned_string
        self.scan_once = json.scanner.py_make_scanner(self)


class _Lines:
    """Turns a character offset into a 1-based line number."""

    def __init__(self, text: str) -> None:
        self._starts = [0]
        self._starts.extend(index + 1 for index, char in enumerate(text) if char == "\n")

    def line_of(self, value: object) -> int | None:
        if not isinstance(value, _PositionedStr):
            return None
        return bisect.bisect_right(self._starts, value.offset)


def _networks_of(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    raise InputError("expected a JSON array of networks or a single network object")


def read(text: str, filename: str) -> list[RangeEntry]:
    try:
        payload = json.loads(text, cls=_PositionDecoder)
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON ({exc.msg})", f"{filename}:{exc.lineno}") from exc

    lines = _Lines(text)
    top_level_list = isinstance(payload, list)
    entries: list[RangeEntry] = []

    for index, network in enumerate(_networks_of(payload)):
        prefix = f"$[{index}]" if top_level_list else "$"
        net_name = str(network.get("Name") or network.get("Id") or f"network #{index}")
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
                line = lines.line_of(value)
                where = f"{filename}:{line}" if line else f"{filename} ({key})"
                entries.append(
                    RangeEntry(
                        source="docker",
                        role="docker-subnet" if field == "Subnet" else "docker-iprange",
                        name=f'docker network "{net_name}" {field}',
                        raw=str(value),
                        networks=(parse_network(value, where),),
                        location=Location(filename, line, key),
                        scope=f"{filename}#{net_name}",
                    )
                )
    return entries
