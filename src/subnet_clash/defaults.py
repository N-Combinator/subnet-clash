"""Well-known default ranges that different tools hand out without being asked.

House rule for this table (from the v0.1 spec): **a row exists only if it carries a link to a
source that documents the range.** Ranges that are folklore-common but that we could not tie to a
published document are deliberately absent -- see README, "What keeps a range out of the table".

Every ``source`` below was fetched and checked to actually mention its range on the day its row
was added: 2026-09-18 for the original rows, 2026-09-19 for ``10.0.0.0/24`` and
``192.168.1.0/24``.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from .model import Network

#: ``assignment`` - a concrete network some tool creates by default.
#: ``pool``       - a block a tool auto-allocates smaller networks out of.
KINDS = ("assignment", "pool")


@dataclass(frozen=True)
class DefaultRange:
    network: Network
    name: str
    kind: str
    source: str


def _n(cidr: str) -> Network:
    return ipaddress.ip_network(cidr)


DEFAULT_RANGES: tuple[DefaultRange, ...] = (
    DefaultRange(
        _n("172.17.0.0/16"),
        "Docker: first default address pool; the default `bridge` network lands here",
        "assignment",
        "https://docs.docker.com/engine/network/",
    ),
    DefaultRange(
        _n("172.18.0.0/16"),
        "Docker: second default address pool (user-defined bridges)",
        "pool",
        "https://docs.docker.com/engine/network/",
    ),
    DefaultRange(
        _n("172.19.0.0/16"),
        "Docker: third default address pool",
        "pool",
        "https://docs.docker.com/engine/network/",
    ),
    DefaultRange(
        _n("172.20.0.0/14"),
        "Docker: fourth default address pool",
        "pool",
        "https://docs.docker.com/engine/network/",
    ),
    DefaultRange(
        _n("172.24.0.0/14"),
        "Docker: fifth default address pool",
        "pool",
        "https://docs.docker.com/engine/network/",
    ),
    DefaultRange(
        _n("172.28.0.0/14"),
        "Docker: sixth default address pool",
        "pool",
        "https://docs.docker.com/engine/network/",
    ),
    DefaultRange(
        _n("192.168.0.0/16"),
        "Docker: last default address pool, carved into /20s",
        "pool",
        "https://docs.docker.com/engine/network/",
    ),
    DefaultRange(
        _n("10.0.0.0/24"),
        "Docker Swarm: lowest /24 of the `10.0.0.0/8` global-scope default pool"
        " that overlay networks are carved out of",
        "assignment",
        "https://github.com/moby/moby/blob/master/daemon/libnetwork/ipamutils/utils.go",
    ),
    DefaultRange(
        _n("10.96.0.0/12"),
        "Kubernetes: kubeadm default service CIDR (`--service-cidr`)",
        "assignment",
        "https://kubernetes.io/docs/reference/setup-tools/kubeadm/kubeadm-init/",
    ),
    DefaultRange(
        _n("10.244.0.0/16"),
        "Flannel: default pod network for the documented kube-flannel manifest",
        "assignment",
        "https://github.com/flannel-io/flannel/blob/master/Documentation/kubernetes.md",
    ),
    DefaultRange(
        _n("192.168.122.0/24"),
        "libvirt: the `default` NAT network created on install"
        " (virbr0, 192.168.122.1/255.255.255.0)",
        "assignment",
        "https://wiki.libvirt.org/VirtualNetworking.html",
    ),
    DefaultRange(
        _n("192.168.1.0/24"),
        "pfSense: the LAN network of a fresh install (192.168.1.1, mask 255.255.255.0);"
        " the classic home-router LAN",
        "assignment",
        "https://docs.netgate.com/pfsense/en/latest/network/subnets.html",
    ),
    DefaultRange(
        _n("192.168.56.0/24"),
        "VirtualBox: default host-only network",
        "assignment",
        "https://www.virtualbox.org/manual/topics/networkingdetails.html",
    ),
    DefaultRange(
        _n("100.64.0.0/10"),
        "Shared address space (CGNAT); Tailscale assigns node addresses from it",
        "pool",
        "https://tailscale.com/kb/1015/100.x-addresses",
    ),
    DefaultRange(
        _n("10.192.122.0/24"),
        "WireGuard: the example tunnel subnet in the wg-quick(8) man page",
        "assignment",
        "https://man7.org/linux/man-pages/man8/wg-quick.8.html",
    ),
    DefaultRange(
        _n("192.168.0.0/24"),
        "dnsmasq: the example `dhcp-range=192.168.0.50,192.168.0.150,12h` from dnsmasq(8)",
        "assignment",
        "https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html",
    ),
    DefaultRange(
        _n("169.254.0.0/16"),
        "IPv4 link-local autoconfiguration, the 169.254/16 prefix; never assign it by hand",
        "assignment",
        "https://www.rfc-editor.org/rfc/rfc3927",
    ),
    DefaultRange(
        _n("fe80::/10"),
        "IPv6 link-local addressing (RFC 4291 §2.5.6)",
        "assignment",
        "https://www.rfc-editor.org/rfc/rfc4291",
    ),
)
