"""One test per config source: what is extracted, and where it is reported from."""

from __future__ import annotations

import pytest

from subnet_clash.errors import InputError
from subnet_clash.sources import get_reader, read_source


def located(entries):
    return {(entry.raw, str(entry.location)) for entry in entries}


# --- WireGuard ------------------------------------------------------------------------------


def test_wireguard_reads_address_and_allowedips(load):
    entries = load("wireguard", "wg0.conf")
    assert located(entries) == {
        ("10.8.0.1/24", "wg0.conf:3"),
        ("10.8.0.2/32", "wg0.conf:10"),
        ("10.8.0.3/32", "wg0.conf:15"),
        ("172.17.5.0/24", "wg0.conf:15"),
    }
    roles = {entry.raw: entry.role for entry in entries}
    assert roles["10.8.0.1/24"] == "interface-address"
    assert roles["172.17.5.0/24"] == "peer-allowedips"


def test_wireguard_interface_address_covers_its_whole_prefix(load):
    address = next(e for e in load("wireguard", "wg0.conf") if e.role == "interface-address")
    assert [str(n) for n in address.networks] == ["10.8.0.0/24"]


def test_wireguard_peers_get_separate_scopes(load):
    entries = load("wireguard", "wg0.conf")
    scopes = {entry.raw: entry.scope for entry in entries}
    assert scopes["10.8.0.2/32"] != scopes["10.8.0.3/32"]
    assert scopes["10.8.0.1/24"] == "wg0.conf#interface"


def test_wireguard_reads_ipv6(load):
    entries = load("wireguard", "ipv6-wg.conf")
    assert located(entries) == {
        ("fd00:50::9/64", "ipv6-wg.conf:2"),
        ("fd00:99::/48", "ipv6-wg.conf:6"),
    }


def test_wireguard_bad_cidr_reports_file_and_line(load):
    with pytest.raises(InputError) as excinfo:
        load("wireguard", "bad/bad-cidr.conf")
    assert "bad/bad-cidr.conf:2" in str(excinfo.value)


def test_wireguard_junk_line_is_rejected():
    with pytest.raises(InputError) as excinfo:
        get_reader("wireguard")("[Interface]\nthis is not a key\n", "wg9.conf")
    assert "wg9.conf:2" in str(excinfo.value)


# --- docker ---------------------------------------------------------------------------------


def test_docker_reads_subnet_and_iprange_with_json_key_and_line(load):
    entries = load("docker", "docker-net.json")
    by_key = {entry.location.key: entry for entry in entries}
    assert by_key["$[0].IPAM.Config[0].Subnet"].raw == "172.17.0.0/16"
    assert by_key["$[0].IPAM.Config[0].Subnet"].location.line == 14
    assert by_key["$[1].IPAM.Config[0].Subnet"].location.line == 36
    assert by_key["$[1].IPAM.Config[0].IPRange"].location.line == 37


def test_docker_gateway_is_not_a_range(load):
    entries = load("docker", "docker-net.json")
    assert all("Gateway" not in (entry.location.key or "") for entry in entries)


def test_docker_networks_are_separate_scopes(load):
    entries = load("docker", "docker-net.json")
    assert {entry.scope for entry in entries} == {
        "docker-net.json#bridge",
        "docker-net.json#lab",
    }


def test_docker_accepts_a_single_network_object():
    payload = '{"Name": "solo", "IPAM": {"Config": [{"Subnet": "10.7.0.0/24"}]}}'
    entries = get_reader("docker")(payload, "solo.json")
    assert entries[0].location.key == "$.IPAM.Config[0].Subnet"


def test_docker_invalid_json_points_at_the_line(load):
    with pytest.raises(InputError) as excinfo:
        load("docker", "bad/broken.json")
    assert "invalid JSON" in str(excinfo.value)
    assert "bad/broken.json:" in str(excinfo.value)


def test_docker_wrong_shape_is_rejected(load):
    with pytest.raises(InputError) as excinfo:
        load("docker", "bad/not-json-networks.json")
    assert "expected a JSON array of networks" in str(excinfo.value)


# --- netplan --------------------------------------------------------------------------------


def test_netplan_reads_addresses_and_routes(load):
    entries = load("netplan", "01-netcfg.yaml")
    assert located(entries) == {
        ("192.168.50.1/24", "01-netcfg.yaml:8"),
        ("172.17.5.0/24", "01-netcfg.yaml:14"),
        ("10.20.0.1/24", "01-netcfg.yaml:18"),
    }
    keys = {entry.location.key for entry in entries}
    assert "network.ethernets.enp3s0.routes[1].to" in keys
    assert "network.bridges.br-lab.addresses[0]" in keys


def test_netplan_skips_nameservers_and_default_routes(load):
    entries = load("netplan", "01-netcfg.yaml")
    raws = {entry.raw for entry in entries}
    assert "1.1.1.1" not in raws and "9.9.9.9" not in raws
    assert "default" not in raws


def test_netplan_devices_are_separate_scopes(load):
    entries = load("netplan", "01-netcfg.yaml")
    assert {entry.scope for entry in entries} == {
        "01-netcfg.yaml#enp3s0",
        "01-netcfg.yaml#br-lab",
    }


def test_netplan_compact_form_and_ipv6(load):
    entries = load("netplan", "netplan-compact.yaml")
    assert located(entries) == {
        ("10.50.0.1/24", "netplan-compact.yaml:6"),
        ("fd00:50::1/64", "netplan-compact.yaml:7"),
    }


def test_netplan_reads_the_address_options_form(load):
    """`- 10.8.0.5/24:` with lifetime/label is an address, not something to drop silently."""
    entries = load("netplan", "netplan-maas.yaml")
    assert located(entries) == {
        ("10.8.0.5/24", "netplan-maas.yaml:9"),
        ("10.8.0.6/24", "netplan-maas.yaml:12"),
        ("10.90.0.0/16", "netplan-maas.yaml:14"),
    }
    keys = {entry.location.key for entry in entries}
    assert "network.ethernets.ens3.addresses[0]" in keys


def test_netplan_reads_flow_mappings_and_multiline_flow_sequences(load):
    """netplan is YAML, so every YAML spelling of a device has to reach the comparison."""
    entries = load("netplan", "netplan-flow.yaml")
    assert located(entries) == {
        ("10.30.0.1/24", "netplan-flow.yaml:7"),
        ("10.31.0.1/24", "netplan-flow.yaml:10"),
        ("10.32.0.1/24", "netplan-flow.yaml:11"),
        ("10.33.0.0/16", "netplan-flow.yaml:14"),
    }


def test_netplan_alias_gives_both_devices_the_anchored_address(load):
    entries = load("netplan", "netplan-flow.yaml")
    scopes = {entry.scope for entry in entries if entry.raw == "10.30.0.1/24"}
    assert scopes == {"netplan-flow.yaml#eth0", "netplan-flow.yaml#eth2"}


def test_netplan_merge_key_is_rejected_not_read_as_an_empty_device(load):
    with pytest.raises(InputError) as excinfo:
        load("netplan", "bad/merge-key.yaml")
    assert "merge keys" in str(excinfo.value)
    assert "bad/merge-key.yaml:9" in str(excinfo.value)


def test_netplan_recursive_anchor_is_rejected(load):
    with pytest.raises(InputError) as excinfo:
        load("netplan", "bad/recursive-anchor.yaml")
    assert "recursive YAML anchor" in str(excinfo.value)


def test_netplan_addresses_must_be_a_list(load):
    with pytest.raises(InputError) as excinfo:
        load("netplan", "bad/addresses-not-a-list.yaml")
    assert "'addresses:' must be a list" in str(excinfo.value)
    assert "bad/addresses-not-a-list.yaml:5" in str(excinfo.value)


def test_netplan_route_target_must_be_a_single_address(load):
    with pytest.raises(InputError) as excinfo:
        load("netplan", "bad/route-to-not-a-scalar.yaml")
    assert "route 'to:' must be a single address" in str(excinfo.value)


def test_netplan_refuses_an_address_item_it_cannot_read(load):
    text = "network:\n  ethernets:\n    eth0:\n      addresses:\n        - - 10.64.0.1/24\n"
    with pytest.raises(InputError) as excinfo:
        get_reader("netplan")(text, "nested.yaml")
    assert "neither an address nor address options" in str(excinfo.value)
    assert "nested.yaml:5" in str(excinfo.value)


def test_netplan_device_group_must_be_a_mapping(load):
    text = "network:\n  ethernets:\n    - eth0\n"
    with pytest.raises(InputError) as excinfo:
        get_reader("netplan")(text, "group.yaml")
    assert "must be a mapping of device name to settings" in str(excinfo.value)


def test_netplan_without_network_key_is_rejected(load):
    with pytest.raises(InputError) as excinfo:
        load("netplan", "bad/no-network.yaml")
    assert "no top-level 'network:' key" in str(excinfo.value)


# --- NetworkManager -------------------------------------------------------------------------


def test_networkmanager_reads_addresses_and_routes(load):
    entries = load("networkmanager", "lab-eth.nmconnection")
    assert located(entries) == {
        ("10.20.0.5/24", "lab-eth.nmconnection:10"),
        ("172.18.0.0/16", "lab-eth.nmconnection:11"),
    }
    keys = {entry.location.key for entry in entries}
    assert keys == {"[ipv4].address1", "[ipv4].route1"}


def test_networkmanager_ignores_dns_and_non_ip_sections(load):
    entries = load("networkmanager", "lab-eth.nmconnection")
    assert all(entry.raw != "1.1.1.1;" for entry in entries)
    assert all("connection" not in (entry.location.key or "") for entry in entries)


# --- dnsmasq --------------------------------------------------------------------------------


def test_dnsmasq_reads_pools_with_line_numbers(load):
    entries = load("dnsmasq", "dnsmasq.conf")
    assert located(entries) == {
        ("192.168.50.200-192.168.51.50", "dnsmasq.conf:6"),
        ("10.8.0.100-10.8.0.150", "dnsmasq.conf:9"),
    }


def test_dnsmasq_pool_is_expanded_into_networks(load):
    pool = next(e for e in load("dnsmasq", "dnsmasq.conf") if e.location.line == 9)
    covered = sum(n.num_addresses for n in pool.networks)
    assert covered == 51  # 10.8.0.100 .. 10.8.0.150 inclusive


def test_dnsmasq_handles_tags_netmask_form_and_ipv6(load):
    entries = load("dnsmasq", "dnsmasq-static.conf")
    assert located(entries) == {
        ("10.60.0.0/255.255.255.0", "dnsmasq-static.conf:1"),
        ("10.61.0.10-10.61.0.20", "dnsmasq-static.conf:2"),
        ("fd00:60::2-fd00:60::500", "dnsmasq-static.conf:3"),
    }
    static = entries[0]
    assert [str(n) for n in static.networks] == ["10.60.0.0/24"]


def test_dnsmasq_ignores_other_directives(load):
    entries = load("dnsmasq", "dnsmasq-static.conf")
    assert all(entry.location.key == "dhcp-range" for entry in entries)


def test_dnsmasq_range_without_an_address_is_rejected():
    with pytest.raises(InputError) as excinfo:
        get_reader("dnsmasq")("dhcp-range=set:red,12h\n", "d.conf")
    assert "d.conf:1" in str(excinfo.value)


# --- reading -------------------------------------------------------------------------------


def test_missing_file_is_reported_by_name(tmp_path):
    with pytest.raises(InputError) as excinfo:
        read_source(str(tmp_path / "nope.conf"))
    assert "no such file" in str(excinfo.value)
