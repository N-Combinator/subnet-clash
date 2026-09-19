"""The well-known-defaults table and the warnings it produces."""

from __future__ import annotations

from conftest import read_fixture
from subnet_clash.analyze import analyze
from subnet_clash.defaults import DEFAULT_RANGES, KINDS


def test_every_row_cites_a_source():
    """House rule from the spec: no source link, no row."""
    for default in DEFAULT_RANGES:
        assert default.source.startswith("https://"), default
        assert default.name.strip()
        assert default.kind in KINDS


def test_rows_are_unique():
    networks = [str(default.network) for default in DEFAULT_RANGES]
    assert len(networks) == len(set(networks))


def test_docker_default_bridge_is_flagged():
    report = analyze(read_fixture("docker", "docker-net.json"))
    hits = {(str(w.entry.location), str(w.default_network), w.relation) for w in report.warnings}
    assert ("docker-net.json:14", "172.17.0.0/16", "identical") in hits


def test_a_range_inside_a_known_default_is_flagged_as_inside():
    report = analyze(read_fixture("wireguard", "wg0.conf"))
    hits = {(w.entry.raw, str(w.default_network), w.relation) for w in report.warnings}
    assert ("172.17.5.0/24", "172.17.0.0/16", "inside") in hits


def test_the_two_ranges_the_spec_names_by_hand_are_flagged():
    """Criterion 4 names 10.0.0.0/24 and 192.168.1.0/24 itself; both carry a cited row."""
    report = analyze(read_fixture("netplan", "typical-lan.yaml"))
    hits = {(w.entry.raw, str(w.default_network), w.relation) for w in report.warnings}
    assert ("10.0.0.9/24", "10.0.0.0/24", "identical") in hits
    assert ("192.168.1.24/24", "192.168.1.0/24", "identical") in hits


def test_a_range_inside_the_swarm_default_is_flagged_as_inside():
    report = analyze(read_fixture("dnsmasq", "dnsmasq-swarm-lan.conf"))
    hits = {(w.entry.raw, str(w.default_network), w.relation) for w in report.warnings}
    assert ("10.0.0.50-10.0.0.150", "10.0.0.0/24", "inside") in hits


def test_a_wireguard_peer_routing_the_home_lan_is_flagged():
    """The home LAN reaches the table from a different source type than the netplan fixture."""
    report = analyze(read_fixture("wireguard", "scenarios/wg-home.conf"))
    hits = {(w.entry.raw, str(w.default_network), w.relation) for w in report.warnings}
    assert ("192.168.1.0/24", "192.168.1.0/24", "identical") in hits


def test_every_warning_carries_the_source_link():
    report = analyze(read_fixture("docker", "docker-net.json"))
    assert report.warnings
    for warning in report.warnings:
        assert warning.default_source.startswith("https://")


def test_defaults_check_can_be_turned_off():
    report = analyze(read_fixture("docker", "docker-net.json"), check_defaults=False)
    assert report.warnings == []


def test_a_range_far_from_any_default_is_not_flagged():
    report = analyze(read_fixture("wireguard", "wg-peers-overlap.conf"))
    assert report.warnings == []
