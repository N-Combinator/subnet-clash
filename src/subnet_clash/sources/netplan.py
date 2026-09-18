"""netplan YAML: interface ``addresses`` and static ``routes[].to``.

``nameservers.addresses`` holds resolver addresses, not local ranges, so it is skipped -- otherwise
every config that points at 8.8.8.8 would "clash" with somebody's 8.8.8.0/24.

Every other shape is either read or refused (exit 2). Quietly skipping a node we do not recognise
would drop an address from the comparison and still report a clean run.
"""

from __future__ import annotations

from ..errors import InputError
from ..model import Location, RangeEntry
from ..ranges import parse_network
from ._yaml import Mapping, Node, Scalar, Sequence, parse

#: netplan groups devices under these keys: ``network.<group>.<device>``
DEVICE_GROUPS = (
    "ethernets",
    "wifis",
    "bridges",
    "bonds",
    "vlans",
    "tunnels",
    "modems",
    "virtual-ethernets",
    "dummy-devices",
    "vrfs",
)

_SKIP_ROUTE_TARGETS = {"default", "0.0.0.0/0", "::/0"}


def _is_empty(node: Node | None) -> bool:
    """True for a key written with no value at all (``eth0:``), which netplan reads as null."""
    return isinstance(node, Scalar) and node.null


def _sequence(node: Node | None, key: str, filename: str) -> Sequence | None:
    if node is None or _is_empty(node):
        return None
    if not isinstance(node, Sequence):
        raise InputError(f"'{key}:' must be a list", f"{filename}:{node.line}")
    return node


def _address(item: Node, filename: str) -> Scalar:
    """One ``addresses:`` item as the address it holds.

    netplan documents two forms. The plain one is ``- 10.100.1.38/24``; the address-options one
    writes the address as a key -- ``- 10.100.1.38/24:`` with ``lifetime``/``label`` nested under
    it -- and is what MAAS generates. Both carry exactly one address, on the item's own line.
    """
    if isinstance(item, Scalar):
        if not item.value:
            raise InputError("empty address", f"{filename}:{item.line}")
        return item
    if isinstance(item, Mapping) and item.items:
        return Scalar(item.line, next(iter(item.items)))
    raise InputError(
        "address list item is neither an address nor address options", f"{filename}:{item.line}"
    )


def _route_target(item: Node, filename: str) -> Scalar | None:
    """A route's destination, or ``None`` when the route carries no range to compare."""
    if not isinstance(item, Mapping):
        raise InputError("route list item must be a mapping", f"{filename}:{item.line}")
    target = item.items.get("to")
    if target is None:
        # A route with no destination (``via:`` plus ``scope:``) has no range to clash with.
        return None
    if not isinstance(target, Scalar):
        raise InputError("route 'to:' must be a single address", f"{filename}:{target.line}")
    if not target.value:
        raise InputError("route 'to:' is empty", f"{filename}:{target.line}")
    if target.value in _SKIP_ROUTE_TARGETS:
        return None
    return target


def _device_entries(device: str, node: Node, filename: str, path: str) -> list[RangeEntry]:
    entries: list[RangeEntry] = []
    if _is_empty(node):
        return entries
    if not isinstance(node, Mapping):
        raise InputError(f"device '{device}' must be a mapping", f"{filename}:{node.line}")
    scope = f"{filename}#{device}"

    addresses = _sequence(node.items.get("addresses"), "addresses", filename)
    if addresses is not None:
        for index, item in enumerate(addresses.items):
            address = _address(item, filename)
            key = f"{path}.addresses[{index}]"
            entries.append(
                RangeEntry(
                    source="netplan",
                    role="netplan-address",
                    name=f"netplan {device} address",
                    raw=address.value,
                    networks=(parse_network(address.value, f"{filename}:{address.line}"),),
                    location=Location(filename, address.line, key),
                    scope=scope,
                )
            )

    routes = _sequence(node.items.get("routes"), "routes", filename)
    if routes is not None:
        for index, item in enumerate(routes.items):
            target = _route_target(item, filename)
            if target is None:
                continue
            key = f"{path}.routes[{index}].to"
            entries.append(
                RangeEntry(
                    source="netplan",
                    role="netplan-route",
                    name=f"netplan {device} route",
                    raw=target.value,
                    networks=(parse_network(target.value, f"{filename}:{target.line}"),),
                    location=Location(filename, target.line, key),
                    scope=scope,
                )
            )
    return entries


def read(text: str, filename: str) -> list[RangeEntry]:
    document = parse(text, filename)
    if document is None:
        return []
    if not isinstance(document, Mapping):
        raise InputError("netplan file must start with a 'network:' mapping", filename)
    network = document.items.get("network")
    if network is None:
        raise InputError("no top-level 'network:' key", filename)
    if not isinstance(network, Mapping):
        raise InputError("'network:' must be a mapping", f"{filename}:{network.line}")

    entries: list[RangeEntry] = []
    for group in DEVICE_GROUPS:
        devices = network.items.get(group)
        if devices is None or _is_empty(devices):
            continue
        if not isinstance(devices, Mapping):
            raise InputError(
                f"'{group}:' must be a mapping of device name to settings",
                f"{filename}:{devices.line}",
            )
        for device, node in devices.items.items():
            entries.extend(_device_entries(device, node, filename, f"network.{group}.{device}"))
    return entries
