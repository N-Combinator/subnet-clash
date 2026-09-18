"""netplan YAML: interface ``addresses`` and static ``routes[].to``.

``nameservers.addresses`` holds resolver addresses, not local ranges, so it is skipped -- otherwise
every config that points at 8.8.8.8 would "clash" with somebody's 8.8.8.0/24.
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


def _device_entries(device: str, node: Node, filename: str, path: str) -> list[RangeEntry]:
    entries: list[RangeEntry] = []
    if not isinstance(node, Mapping):
        return entries
    scope = f"{filename}#{device}"

    addresses = node.items.get("addresses")
    if isinstance(addresses, Sequence):
        for index, item in enumerate(addresses.items):
            if not isinstance(item, Scalar) or not item.value:
                continue
            key = f"{path}.addresses[{index}]"
            entries.append(
                RangeEntry(
                    source="netplan",
                    role="netplan-address",
                    name=f"netplan {device} address",
                    raw=item.value,
                    networks=(parse_network(item.value, f"{filename}:{item.line}"),),
                    location=Location(filename, item.line, key),
                    scope=scope,
                )
            )

    routes = node.items.get("routes")
    if isinstance(routes, Sequence):
        for index, item in enumerate(routes.items):
            if not isinstance(item, Mapping):
                continue
            target = item.items.get("to")
            if not isinstance(target, Scalar) or target.value in _SKIP_ROUTE_TARGETS:
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
        if not isinstance(devices, Mapping):
            continue
        for device, node in devices.items.items():
            entries.extend(_device_entries(device, node, filename, f"network.{group}.{device}"))
    return entries
