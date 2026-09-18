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
    assert "tab used for indentation" in err


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
