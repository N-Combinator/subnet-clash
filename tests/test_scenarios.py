"""The two situations the tool was written for, rebuilt from fixture files.

Each one is a thread quoted in `docs/motivation.md`; the fixtures under `fixtures/scenarios/` are
the configs the author of that thread would have had on disk, and the test asserts subnet-clash
finds the collision they were debugging by hand, naming both sides with a file and a line.
"""

from __future__ import annotations

import json

from conftest import fixture_path
from subnet_clash.cli import EXIT_CLASH, main


def check(capsys, argv):
    code = main(["check", *argv, "--format", "json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def sides(clash):
    return (clash["a"]["location"], clash["b"]["location"])


def test_wireguard_home_lan_versus_the_remote_wifi(capsys):
    """r/WireGuard, 2026-03-11, fabb24: the remote Wi-Fi uses the home 192.168.1.0/24 too.

    The laptop routes 192.168.1.0/24 over the tunnel while sitting on a Wi-Fi network that hands
    out the same block, so the LAN at home is unreachable from the remote side.
    """
    code, report, _err = check(
        capsys,
        [
            "--wg",
            fixture_path("scenarios/wg-home.conf"),
            "--netplan",
            fixture_path("scenarios/remote-wifi.yaml"),
        ],
    )
    assert code == EXIT_CLASH

    found = [c for c in report["clashes"] if "192.168.1" in c["a"]["range"] + c["b"]["range"]]
    assert len(found) == 1
    clash = found[0]
    assert clash["kind"] == "identical"
    assert clash["intersection"] == ["192.168.1.0/24"]

    by_source = {side["source"]: side for side in (clash["a"], clash["b"])}
    assert by_source["wireguard"]["range"] == "192.168.1.0/24"
    assert by_source["wireguard"]["line"] == 9  # AllowedIPs
    assert by_source["wireguard"]["key"] == "[Peer].AllowedIPs"
    assert by_source["netplan"]["range"] == "192.168.1.34/24"
    assert by_source["netplan"]["line"] == 9  # the address on wlan0
    assert by_source["netplan"]["key"] == "network.wifis.wlan0.addresses[0]"

    # The tunnel's own subnet is not part of the collision and must not be reported as one.
    assert all("10.9.0" not in c["a"]["range"] + c["b"]["range"] for c in report["clashes"])


def test_docker_container_veth_versus_the_host_lan(capsys):
    """r/homelab, 2026-05-18, mattjh_: a container veth on a subnet that overlaps the host's.

    The container network is a /20 out of docker's last default pool; the host's LAN is a /24
    sitting inside it, which is the overlap behind the "deeply cursed ECMP behaviour".
    """
    code, report, _err = check(
        capsys,
        [
            "--docker",
            fixture_path("scenarios/docker-veth.json"),
            "--netplan",
            fixture_path("scenarios/host-lan.yaml"),
        ],
    )
    assert code == EXIT_CLASH
    assert len(report["clashes"]) == 1

    clash = report["clashes"][0]
    assert clash["kind"] == "contains"
    assert clash["intersection"] == ["192.168.20.0/24"]

    by_source = {side["source"]: side for side in (clash["a"], clash["b"])}
    assert by_source["docker"]["range"] == "192.168.16.0/20"
    assert by_source["docker"]["line"] == 11
    assert by_source["docker"]["key"] == "$[0].IPAM.Config[0].Subnet"
    assert by_source["netplan"]["range"] == "192.168.20.10/24"
    assert by_source["netplan"]["line"] == 8
    assert by_source["netplan"]["key"] == "network.ethernets.eno1.addresses[0]"

    # The docker side is the outer range, and the report says which side that is.
    outer = clash["a"] if clash["container"] == "a" else clash["b"]
    assert outer["source"] == "docker"

    # It is also a range docker hands out unprompted, which is its own warning.
    pools = {w["default"]["network"] for w in report["default_range_warnings"]}
    assert "192.168.0.0/16" in pools


def test_each_scenario_names_both_files_in_the_markdown_report(capsys):
    """The Markdown a human reads has to carry both file:line pairs, not just the JSON."""
    code = main(
        [
            "check",
            "--docker",
            fixture_path("scenarios/docker-veth.json"),
            "--netplan",
            fixture_path("scenarios/host-lan.yaml"),
        ]
    )
    out = capsys.readouterr().out
    assert code == EXIT_CLASH
    assert "docker-veth.json:11" in out
    assert "host-lan.yaml:8" in out
    assert "contains" in out
