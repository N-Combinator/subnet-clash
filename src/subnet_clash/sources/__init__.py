"""Readers that turn config files into :class:`~subnet_clash.model.RangeEntry` lists.

Every reader takes text that has already been read from disk (or stdin). Nothing in this package
opens a socket, runs a command, or looks at the live system: v0.1 only ever sees files you hand it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from ..errors import InputError
from ..model import RangeEntry

SOURCE_TYPES = ("wireguard", "docker", "netplan", "networkmanager", "dnsmasq")

#: Display name used for ``-`` in locations and messages.
STDIN = "<stdin>"

Reader = Callable[[str, str], list[RangeEntry]]


def _read_stdin() -> str:
    """Read stdin as UTF-8, reporting a decode failure the same way a file does.

    ``docker network inspect ... | subnet-clash check --docker -`` is the pipeline this exists
    for, so bad bytes have to come out as exit 2 and not as a traceback (exit 1 already means
    "clash found").
    """
    buffer = getattr(sys.stdin, "buffer", None)
    try:
        if buffer is None:  # a text-only stand-in, e.g. a patched stdin in tests
            return sys.stdin.read()
        return buffer.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"not UTF-8 text ({exc.reason})", STDIN) from exc
    except OSError as exc:
        raise InputError(f"cannot read stdin ({exc.strerror})", STDIN) from exc


def read_source(path: str) -> tuple[str, str]:
    """Return ``(display_name, text)``. ``-`` reads stdin, everything else is a real file."""
    if path == "-":
        return STDIN, _read_stdin()
    try:
        with open(path, encoding="utf-8") as handle:
            return path, handle.read()
    except FileNotFoundError as exc:
        raise InputError("no such file", path) from exc
    except IsADirectoryError as exc:
        raise InputError("is a directory, expected a file", path) from exc
    except OSError as exc:
        raise InputError(f"cannot read file ({exc.strerror})", path) from exc
    except UnicodeDecodeError as exc:
        raise InputError(f"not UTF-8 text ({exc.reason})", path) from exc


def get_reader(source_type: str) -> Reader:
    from . import dnsmasq, docker, netplan, networkmanager, wireguard

    readers: dict[str, Reader] = {
        "wireguard": wireguard.read,
        "docker": docker.read,
        "netplan": netplan.read,
        "networkmanager": networkmanager.read,
        "dnsmasq": dnsmasq.read,
    }
    return readers[source_type]
