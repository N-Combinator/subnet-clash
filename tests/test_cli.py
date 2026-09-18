"""End-to-end CLI behaviour: exit codes, both report formats, stdin, and bad input."""

from __future__ import annotations

import json

import pytest

from conftest import fixture_path
from subnet_clash.cli import EXIT_CLASH, EXIT_INPUT_ERROR, EXIT_OK, main

ALL_SOURCES = [
    "check",
    "--wg",
    fixture_path("wg0.conf"),
    "--docker",
    fixture_path("docker-net.json"),
    "--netplan",
    fixture_path("01-netcfg.yaml"),
    "--nm",
    fixture_path("lab-eth.nmconnection"),
    "--dnsmasq",
    fixture_path("dnsmasq.conf"),
]


def run(capsys, argv):
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --- exit codes -----------------------------------------------------------------------------


def test_clash_exits_one(capsys):
    code, out, _err = run(capsys, ALL_SOURCES)
    assert code == EXIT_CLASH
    assert "clash(es)" in out


def test_clean_run_exits_zero(capsys):
    code, out, _err = run(
        capsys, ["check", "--wg", fixture_path("wg-peers-overlap.conf"), "--format", "json"]
    )
    payload = json.loads(out)
    assert payload["summary"]["clashes"] == 1
    assert code == EXIT_CLASH

    code, out, _err = run(capsys, ["check", "--docker", fixture_path("docker-net.json")])
    assert code == EXIT_OK
    assert "No clashes found." in out


def test_missing_file_exits_two_with_a_message(capsys):
    code, out, err = run(capsys, ["check", "--wg", fixture_path("does-not-exist.conf")])
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "no such file" in err and "does-not-exist.conf" in err


def test_broken_json_exits_two_with_a_location(capsys):
    code, _out, err = run(capsys, ["check", "--docker", fixture_path("bad/broken.json")])
    assert code == EXIT_INPUT_ERROR
    assert "invalid JSON" in err


def test_bad_cidr_exits_two(capsys):
    code, _out, err = run(capsys, ["check", "--wg", fixture_path("bad/bad-cidr.conf")])
    assert code == EXIT_INPUT_ERROR
    assert "not an IP network" in err


def test_tab_indented_yaml_exits_two(capsys):
    code, _out, err = run(capsys, ["check", "--netplan", fixture_path("bad/tabs.yaml")])
    assert code == EXIT_INPUT_ERROR
    assert "invalid YAML" in err and "tabs.yaml:2" in err


def test_multi_document_netplan_exits_two(capsys):
    code, out, err = run(capsys, ["check", "--netplan", fixture_path("bad/multi-doc.yaml")])
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "multiple YAML documents" in err


def test_concatenated_netplan_files_exit_two(capsys):
    code, out, err = run(capsys, ["check", "--netplan", fixture_path("bad/concatenated.yaml")])
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "duplicate key 'network'" in err


def test_merge_key_netplan_exits_two_instead_of_reading_zero_addresses(capsys):
    code, out, err = run(capsys, ["check", "--netplan", fixture_path("bad/merge-key.yaml")])
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "merge keys" in err


def test_anchor_bomb_netplan_exits_two_instead_of_expanding(capsys):
    code, out, err = run(capsys, ["check", "--netplan", fixture_path("bad/anchor-bomb.yaml")])
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "expands to more than" in err


def test_deeply_nested_netplan_exits_two_instead_of_a_traceback(capsys):
    """Thousands of nested sequences exhaust the composer's stack; that is still exit 2."""
    code, out, err = run(capsys, ["check", "--netplan", fixture_path("bad/deep-nesting.yaml")])
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "nests too deeply" in err
    assert "deep-nesting.yaml" in err


def test_deeply_nested_docker_json_exits_two(capsys):
    """The JSON side is recursive too, so it gets the same answer, not a RecursionError."""
    code, out, err = run(capsys, ["check", "--docker", fixture_path("bad/deep-nesting.json")])
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "nests too deeply" in err
    assert "deep-nesting.json" in err


def test_recursion_error_outside_the_readers_still_exits_two(capsys, monkeypatch):
    """The net under everything else: no path out of main() may raise RecursionError."""

    def boom(*_args, **_kwargs):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr("subnet_clash.cli.analyze", boom)
    code, out, err = run(capsys, ["check", "--wg", fixture_path("wg0.conf")])
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "nests too deeply" in err


def test_flow_written_netplan_is_compared_not_skipped(capsys):
    """Flow mappings, multi-line flow sequences and aliases all have to reach the comparison."""
    code, out, _err = run(
        capsys, ["check", "--netplan", fixture_path("netplan-flow.yaml"), "--format", "json"]
    )
    assert code == EXIT_CLASH
    payload = json.loads(out)
    assert payload["summary"]["ranges"] == 5
    # eth0's anchored address and eth2's alias to it are the same block on two devices.
    identical = [c for c in payload["clashes"] if c["kind"] == "identical"]
    assert [c["a"]["range"] for c in identical] == ["10.30.0.1/24"]


def test_netplan_address_options_are_compared_not_dropped(capsys):
    """The MAAS `- 10.8.0.5/24:` form must reach the comparison, not vanish into a clean run."""
    code, out, _err = run(
        capsys,
        [
            "check",
            "--netplan",
            fixture_path("netplan-maas.yaml"),
            "--docker",
            fixture_path("docker-net.json"),
            "--format",
            "json",
        ],
    )
    assert code == EXIT_CLASH
    payload = json.loads(out)
    lines = {c["a"]["line"] for c in payload["clashes"]} | {
        c["b"]["line"] for c in payload["clashes"]
    }
    assert 9 in lines


def test_netplan_addresses_that_are_not_a_list_exit_two(capsys):
    code, out, err = run(
        capsys, ["check", "--netplan", fixture_path("bad/addresses-not-a-list.yaml")]
    )
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "'addresses:' must be a list" in err


def test_an_unknown_netplan_group_still_reaches_the_comparison(capsys):
    """The address lives under a group the tool does not know; it must still be compared."""
    code, out, err = run(
        capsys,
        [
            "check",
            "--netplan",
            fixture_path("netplan-unknown-group.yaml"),
            "--wg",
            fixture_path("wg-ovs-peer.conf"),
            "--format",
            "json",
        ],
    )
    assert code == EXIT_CLASH
    payload = json.loads(out)
    pairs = {(c["kind"], c["a"]["range"], c["b"]["range"]) for c in payload["clashes"]}
    assert ("identical", "10.44.0.1/24", "10.44.0.0/24") in pairs
    assert "'network.ovs-bridges:'" in err


def test_a_source_that_yields_no_ranges_is_reported_on_stderr(capsys, tmp_path):
    empty = tmp_path / "wg-nothing.conf"
    empty.write_text("[Interface]\nPrivateKey = x\n", encoding="utf-8")
    code, _out, err = run(capsys, ["check", "--wg", str(empty)])
    assert code == EXIT_OK
    assert "no ranges found" in err


def test_an_undetermined_dnsmasq_range_is_reported_and_never_compared(capsys):
    """A /32 guessed from ``10.60.0.0,static`` would have "clashed" with the peer's /24."""
    argv = [
        "check",
        "--dnsmasq",
        fixture_path("dnsmasq-nomask.conf"),
        "--wg",
        fixture_path("wg-lab.conf"),
    ]
    code, out, err = run(capsys, [*argv, "--format", "json"])
    assert code == EXIT_OK
    payload = json.loads(out)
    assert payload["clashes"] == []
    assert payload["summary"]["undetermined"] == 1
    undetermined = payload["undetermined_ranges"]
    assert [(u["range"], u["line"]) for u in undetermined] == [("10.60.0.0", 2)]
    assert "comes from the interface" in undetermined[0]["undetermined"]
    assert "comes from the interface" in err

    code, out, _err = run(capsys, argv)
    assert code == EXIT_OK
    assert "## Undetermined ranges" in out
    assert "`10.60.0.0`" in out


def test_no_sources_exits_two(capsys):
    code, _out, err = run(capsys, ["check"])
    assert code == EXIT_INPUT_ERROR
    assert "no source files given" in err


def test_unknown_flag_exits_two():
    with pytest.raises(SystemExit) as excinfo:
        main(["check", "--router", "x"])
    assert excinfo.value.code == EXIT_INPUT_ERROR


# --- report formats -------------------------------------------------------------------------


def test_json_report_shape(capsys):
    code, out, _err = run(capsys, [*ALL_SOURCES, "--format", "json"])
    assert code == EXIT_CLASH
    payload = json.loads(out)
    assert payload["tool"] == "subnet-clash"
    assert {s["type"] for s in payload["sources"]} == {
        "wireguard",
        "docker",
        "netplan",
        "networkmanager",
        "dnsmasq",
    }
    summary = payload["summary"]
    assert summary["clashes"] == len(payload["clashes"]) > 0
    assert summary["overlap"] + summary["identical"] + summary["contains"] == summary["clashes"]

    clash = payload["clashes"][0]
    assert clash["kind"] in ("overlap", "identical", "contains")
    for side in ("a", "b"):
        assert clash[side]["file"]
        assert clash[side]["line"]
        assert clash[side]["location"].endswith(str(clash[side]["line"]))
    assert payload["default_range_warnings"][0]["default"]["source"].startswith("https://")


def test_json_report_names_both_sides_of_a_docker_vs_wireguard_clash(capsys):
    _code, out, _err = run(capsys, [*ALL_SOURCES, "--format", "json"])
    payload = json.loads(out)
    pairs = {
        (c["a"]["location"].split("/")[-1], c["b"]["location"].split("/")[-1], c["kind"])
        for c in payload["clashes"]
    }
    assert ("docker-net.json:14", "wg0.conf:15", "contains") in pairs


def test_markdown_report_shows_both_locations_and_the_kind(capsys):
    _code, out, _err = run(capsys, ALL_SOURCES)
    assert "# subnet-clash report" in out
    assert "## Clashes" in out
    assert "## Well-known default ranges in use" in out
    assert "vs" in out
    assert "docker-net.json:14" in out and "wg0.conf:15" in out


def test_output_file(capsys, tmp_path):
    target = tmp_path / "report.json"
    code, out, _err = run(capsys, [*ALL_SOURCES, "--format", "json", "-o", str(target)])
    assert code == EXIT_CLASH
    assert out == ""
    assert json.loads(target.read_text())["tool"] == "subnet-clash"


# --- stdin ----------------------------------------------------------------------------------


def test_docker_json_can_come_from_stdin(capsys, monkeypatch):
    import io
    from pathlib import Path

    payload = Path(fixture_path("docker-net.json")).read_text(encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    code, out, _err = run(
        capsys,
        ["check", "--docker", "-", "--wg", fixture_path("wg0.conf"), "--format", "json"],
    )
    assert code == EXIT_CLASH
    parsed = json.loads(out)
    assert any(source["file"] == "<stdin>" for source in parsed["sources"])
    assert any("<stdin>" in (clash["a"]["file"], clash["b"]["file"]) for clash in parsed["clashes"])


def test_non_utf8_stdin_exits_two_not_one(capsys, monkeypatch):
    import io

    # Exit 1 means "clash found", so a decode failure must not come out as 1 (or as a traceback):
    # a CI job piping `docker network inspect` in could not tell the two apart.
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b'[{"Name": "\xb7bad"}]')))
    code, out, err = run(capsys, ["check", "--docker", "-"])
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "<stdin>" in err and "not UTF-8" in err


def test_stdin_can_only_be_used_once(capsys):
    code, _out, err = run(capsys, ["check", "--docker", "-", "--wg", "-"])
    assert code == EXIT_INPUT_ERROR
    assert "stdin" in err


# --- flags ----------------------------------------------------------------------------------


def test_no_default_check_drops_the_warnings(capsys):
    _code, out, _err = run(capsys, [*ALL_SOURCES, "--format", "json", "--no-default-check"])
    assert json.loads(out)["default_range_warnings"] == []


def test_include_default_routes(capsys):
    args = [
        "check",
        "--wg",
        fixture_path("fulltunnel.conf"),
        "--netplan",
        fixture_path("netplan-compact.yaml"),
        "--format",
        "json",
    ]
    assert json.loads(run(capsys, args)[1])["summary"]["skipped_default_routes"] == 2
    code, out, _err = run(capsys, [*args, "--include-default-routes"])
    assert code == EXIT_CLASH
    assert json.loads(out)["summary"]["skipped_default_routes"] == 0


def test_include_default_routes_covers_netplan_and_networkmanager(capsys):
    """The flag promises 0.0.0.0/0 and ::/0; the readers must not have thrown them away first."""
    args = [
        "check",
        "--netplan",
        fixture_path("01-netcfg.yaml"),
        "--nm",
        fixture_path("lab-eth.nmconnection"),
        "--format",
        "json",
    ]
    skipped = json.loads(run(capsys, args)[1])["skipped_default_routes"]
    assert {entry["file"].split("/")[-1] for entry in skipped} == {
        "01-netcfg.yaml",
        "lab-eth.nmconnection",
    }

    payload = json.loads(run(capsys, [*args, "--include-default-routes"])[1])
    assert payload["summary"]["skipped_default_routes"] == 0
    # Both default routes now sit on the table and contain every other range there.
    contained = {c["a"]["range"] for c in payload["clashes"] if c["kind"] == "contains"} | {
        c["b"]["range"] for c in payload["clashes"] if c["kind"] == "contains"
    }
    assert {"default", "0.0.0.0/0"} <= contained


# --- defaults subcommand --------------------------------------------------------------------


def test_defaults_table_every_row_has_a_source(capsys):
    code, out, _err = run(capsys, ["defaults"])
    assert code == EXIT_OK
    rows = [line for line in out.splitlines() if line.startswith("| `")]
    assert rows
    for row in rows:
        assert "https://" in row


def test_defaults_json(capsys):
    code, out, _err = run(capsys, ["defaults", "--format", "json"])
    assert code == EXIT_OK
    rows = json.loads(out)["default_ranges"]
    assert rows and all(row["source"].startswith("https://") for row in rows)
