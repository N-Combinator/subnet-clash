"""The bundled YAML subset reader: what it accepts, and how loudly it refuses the rest."""

from __future__ import annotations

import pytest

from subnet_clash.errors import InputError
from subnet_clash.sources._yaml import Mapping, Scalar, Sequence, parse


def test_block_mapping_sequence_and_line_numbers():
    doc = parse(
        "network:\n"
        "  ethernets:\n"
        "    eth0:\n"
        "      addresses:\n"
        "        - 10.0.0.1/24\n"
        "        - 10.0.1.1/24\n",
        "x.yaml",
    )
    eth0 = doc.items["network"].items["ethernets"].items["eth0"]
    addresses = eth0.items["addresses"]
    assert isinstance(addresses, Sequence)
    assert [item.value for item in addresses.items] == ["10.0.0.1/24", "10.0.1.1/24"]
    assert [item.line for item in addresses.items] == [5, 6]


def test_sequence_may_sit_at_the_same_indent_as_its_key():
    doc = parse("addresses:\n- 10.0.0.1/24\n", "x.yaml")
    assert [item.value for item in doc.items["addresses"].items] == ["10.0.0.1/24"]


def test_flow_sequence_quotes_and_comments():
    doc = parse('addresses: [10.0.0.1/24, "10.0.2.1/24"]  # two of them\n', "x.yaml")
    assert [item.value for item in doc.items["addresses"].items] == ["10.0.0.1/24", "10.0.2.1/24"]
    assert all(item.line == 1 for item in doc.items["addresses"].items)


def test_ipv6_value_is_not_mistaken_for_a_key():
    doc = parse("routes:\n  - to: fd00::/64\n    via: fd00::1\n", "x.yaml")
    route = doc.items["routes"].items[0]
    assert isinstance(route, Mapping)
    assert route.items["to"].value == "fd00::/64"
    assert route.items["via"].value == "fd00::1"


def test_scalar_item_keeps_its_own_line():
    doc = parse("a:\n  b: 1\nc: 2\n", "x.yaml")
    assert isinstance(doc.items["c"], Scalar)
    assert doc.items["c"].line == 3


def test_empty_document_is_none():
    assert parse("# only a comment\n\n", "x.yaml") is None


def test_tab_indentation_is_rejected():
    with pytest.raises(InputError) as excinfo:
        parse("network:\n\tversion: 2\n", "x.yaml")
    assert "tab" in str(excinfo.value)
    assert "x.yaml:2" in str(excinfo.value)


def test_line_without_a_key_is_rejected():
    with pytest.raises(InputError) as excinfo:
        parse("network:\n  version 2\n", "x.yaml")
    assert "expected 'key: value'" in str(excinfo.value)


def test_a_single_document_may_be_wrapped_in_markers():
    doc = parse("---\nnetwork:\n  version: 2\n...\n", "x.yaml")
    assert doc.items["network"].items["version"].value == "2"


def test_second_document_is_rejected():
    with pytest.raises(InputError) as excinfo:
        parse("network:\n  version: 2\n---\nnetwork:\n  version: 2\n", "x.yaml")
    assert "multiple YAML documents" in str(excinfo.value)
    assert "x.yaml:3" in str(excinfo.value)


def test_content_after_the_end_marker_is_rejected():
    with pytest.raises(InputError) as excinfo:
        parse("network:\n  version: 2\n...\nnetwork:\n  version: 2\n", "x.yaml")
    assert "multiple YAML documents" in str(excinfo.value)
    assert "x.yaml:4" in str(excinfo.value)


def test_duplicate_key_is_rejected():
    with pytest.raises(InputError) as excinfo:
        parse("network:\n  version: 2\nnetwork:\n  version: 2\n", "x.yaml")
    assert "duplicate key 'network'" in str(excinfo.value)
    assert "x.yaml:3" in str(excinfo.value)


def test_duplicate_key_is_rejected_nested_and_inline():
    with pytest.raises(InputError) as excinfo:
        parse("eth0:\n  addresses: [10.0.0.1/24]\n  addresses:\n    - 10.0.1.1/24\n", "x.yaml")
    assert "duplicate key 'addresses'" in str(excinfo.value)
    assert "x.yaml:3" in str(excinfo.value)
