"""Classification (overlap / contains / identical) and what deliberately is not a clash."""

from __future__ import annotations

import ipaddress

from conftest import read_fixture
from subnet_clash.analyze import analyze, find_clashes
from subnet_clash.ranges import relation


def net(*cidrs):
    return [ipaddress.ip_network(c) for c in cidrs]


def kinds(clashes):
    return {(str(c.a.location), str(c.b.location), c.kind) for c in clashes}


def test_relation_distinguishes_partial_overlap_from_containment():
    assert relation(net("10.1.2.0/24"), net("10.0.0.0/8"))[0] == "contains"
    assert relation(net("10.0.0.0/24"), net("10.0.0.0/24"))[0] == "identical"
    assert relation(net("10.0.0.0/24"), net("10.1.0.0/24"))[0] is None
    # neither side is inside the other: two half-overlapping multi-network sets
    kind, shared, _ = relation(net("10.0.0.0/24", "10.0.1.0/24"), net("10.0.1.0/24", "10.0.2.0/24"))
    assert kind == "overlap"
    assert [str(n) for n in shared] == ["10.0.1.0/24"]


def test_contains_records_which_side_is_the_outer_one():
    kind, _shared, container = relation(net("10.0.0.0/8"), net("10.1.2.0/24"))
    assert (kind, container) == ("contains", "left")


def test_ipv4_and_ipv6_never_collide():
    assert relation(net("0.0.0.0/0"), net("::/0"))[0] is None


def test_all_three_kinds_are_found_across_the_four_sources():
    entries = (
        read_fixture("wireguard", "wg0.conf")
        + read_fixture("docker", "docker-net.json")
        + read_fixture("netplan", "01-netcfg.yaml")
        + read_fixture("dnsmasq", "dnsmasq.conf")
    )
    found = kinds(analyze(entries).clashes)
    # partial overlap: the DHCP pool runs past the /24 the interface owns
    assert ("01-netcfg.yaml:8", "dnsmasq.conf:6", "overlap") in found
    # identical: the same /24 configured as a docker network and as the tunnel subnet
    assert ("docker-net.json:36", "wg0.conf:3", "identical") in found
    # contains: the DHCP pool sits inside the tunnel subnet - usually on purpose
    assert ("dnsmasq.conf:9", "wg0.conf:3", "contains") in found
    # contains: a peer route inside docker's default bridge network
    assert ("docker-net.json:14", "wg0.conf:15", "contains") in found


def test_every_clash_names_a_file_and_line_on_both_sides():
    entries = read_fixture("wireguard", "wg0.conf") + read_fixture("docker", "docker-net.json")
    clashes = analyze(entries).clashes
    assert clashes
    for clash in clashes:
        for side in (clash.a, clash.b):
            assert side.location.file
            assert side.location.line is not None
            assert str(side.location) == f"{side.location.file}:{side.location.line}"


def test_wireguard_interface_and_its_own_peers_are_not_a_clash():
    entries = read_fixture("wireguard", "wg0.conf")
    assert find_clashes(entries) == []


def test_two_peers_of_one_tunnel_overlapping_is_a_clash():
    entries = read_fixture("wireguard", "wg-peers-overlap.conf")
    clashes = find_clashes(entries)
    assert kinds(clashes) == {("wg-peers-overlap.conf:6", "wg-peers-overlap.conf:10", "contains")}


def test_docker_iprange_inside_its_own_subnet_is_not_a_clash():
    entries = read_fixture("docker", "docker-net.json")
    assert find_clashes(entries) == []


def test_netplan_route_under_its_own_device_is_not_a_clash():
    entries = read_fixture("netplan", "01-netcfg.yaml")
    # The device's addresses and its own routes share a scope. The `to: default` route the same
    # file carries is read too, and set aside by analyze the way a full-tunnel AllowedIPs is --
    # without that, it would contain every other range in the file.
    report = analyze(entries)
    assert report.clashes == []
    assert [entry.raw for entry in report.skipped_default_routes] == ["default"]


def test_default_routes_are_skipped_unless_asked_for():
    entries = read_fixture("wireguard", "fulltunnel.conf") + read_fixture(
        "netplan", "netplan-compact.yaml"
    )
    report = analyze(entries)
    assert report.clashes == []
    assert {entry.raw for entry in report.skipped_default_routes} == {"0.0.0.0/0", "::/0"}

    with_defaults = analyze(entries, include_default_routes=True)
    assert with_defaults.skipped_default_routes == []
    assert {c.kind for c in with_defaults.clashes} == {"contains"}
    assert len(with_defaults.clashes) == 2  # one v4 pair, one v6 pair


def test_ipv6_ranges_clash_with_each_other():
    entries = read_fixture("wireguard", "ipv6-wg.conf") + read_fixture(
        "netplan", "netplan-compact.yaml"
    )
    assert kinds(analyze(entries).clashes) == {
        ("ipv6-wg.conf:2", "netplan-compact.yaml:7", "identical")
    }
