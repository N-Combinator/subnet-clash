"""The PyYAML-backed node layer: what it hands the readers, and where it says things sit."""

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


def test_flow_mapping_is_a_mapping_not_opaque_text():
    doc = parse("eth0: {addresses: [10.0.0.1/24], dhcp4: false}\n", "x.yaml")
    eth0 = doc.items["eth0"]
    assert isinstance(eth0, Mapping)
    assert [item.value for item in eth0.items["addresses"].items] == ["10.0.0.1/24"]
    assert eth0.items["dhcp4"].value == "false"


def test_multiline_flow_sequence_keeps_every_item_on_its_own_line():
    doc = parse("addresses: [\n  10.0.0.1/24,\n  10.0.1.1/24,\n]\n", "x.yaml")
    items = doc.items["addresses"].items
    assert [(item.value, item.line) for item in items] == [
        ("10.0.0.1/24", 2),
        ("10.0.1.1/24", 3),
    ]


def test_nested_sequences_keep_their_items_and_lines():
    doc = parse("groups:\n  - - 10.0.0.1/24\n    - 10.0.1.1/24\n  - - 10.0.2.1/24\n", "x.yaml")
    outer = doc.items["groups"]
    assert [[item.value for item in inner.items] for inner in outer.items] == [
        ["10.0.0.1/24", "10.0.1.1/24"],
        ["10.0.2.1/24"],
    ]
    assert [inner.line for inner in outer.items] == [2, 4]
    assert [item.line for item in outer.items[0].items] == [2, 3]


def test_a_sequence_of_mappings_does_not_lose_the_items_after_the_first():
    doc = parse(
        "routes:\n  - to: 10.0.0.0/8\n    via: 10.1.0.1\n  - to: 10.2.0.0/16\n    via: 10.1.0.1\n",
        "x.yaml",
    )
    routes = doc.items["routes"]
    assert [route.items["to"].value for route in routes.items] == ["10.0.0.0/8", "10.2.0.0/16"]
    assert [route.items["to"].line for route in routes.items] == [2, 4]


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


def test_a_key_with_no_value_is_null_not_an_empty_string():
    doc = parse('eth0:\nlabel: ""\n', "x.yaml")
    assert doc.items["eth0"].null is True
    assert doc.items["label"].null is False and doc.items["label"].value == ""


def test_empty_document_is_none():
    assert parse("# only a comment\n\n", "x.yaml") is None


def test_tab_indentation_is_rejected_with_a_location():
    with pytest.raises(InputError) as excinfo:
        parse("network:\n\tversion: 2\n", "x.yaml")
    assert "invalid YAML" in str(excinfo.value)
    assert "x.yaml:2" in str(excinfo.value)


def test_a_single_document_may_be_wrapped_in_markers():
    doc = parse("---\nnetwork:\n  version: 2\n...\n", "x.yaml")
    assert doc.items["network"].items["version"].value == "2"


def test_second_document_is_rejected():
    with pytest.raises(InputError) as excinfo:
        parse("network:\n  version: 2\n---\nnetwork:\n  version: 2\n", "x.yaml")
    assert "multiple YAML documents" in str(excinfo.value)
    assert "x.yaml:4" in str(excinfo.value)


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


def test_an_alias_is_resolved_to_the_anchored_value():
    doc = parse("eth0:\n  addresses: &lan [10.77.0.1/24]\neth1:\n  addresses: *lan\n", "x.yaml")
    eth1 = doc.items["eth1"].items["addresses"]
    assert [item.value for item in eth1.items] == ["10.77.0.1/24"]
    # The value is written once, on line 2, and that is where both sides are reported from.
    assert [item.line for item in eth1.items] == [2]


def test_a_merge_key_is_rejected_rather_than_read_as_a_key_called_double_angle():
    with pytest.raises(InputError) as excinfo:
        parse("defaults: &d\n  addresses: [10.0.0.1/24]\neth0:\n  <<: *d\n", "x.yaml")
    assert "merge keys" in str(excinfo.value)
    assert "x.yaml:4" in str(excinfo.value)


def test_a_recursive_anchor_is_rejected_instead_of_recursing_forever():
    with pytest.raises(InputError) as excinfo:
        parse("a: &loop\n  b: *loop\n", "x.yaml")
    assert "recursive YAML anchor" in str(excinfo.value)


def test_a_quoted_star_is_still_an_ordinary_string():
    doc = parse("search: ['*.example.com']\n", "x.yaml")
    assert [item.value for item in doc.items["search"].items] == ["*.example.com"]
