"""netplan YAML read with PyYAML, keeping the line number of every node.

netplan files are YAML, so they are parsed by a YAML library rather than by a hand-written
subset reader. The one thing ``yaml.safe_load`` throws away is *where* each value sat, and every
finding has to name ``file:line`` on both sides -- so the stream is composed into a node tree
(:func:`yaml.compose_all`) and the composer's start marks are carried into the three small node
types below, which is all the readers need to walk.

PyYAML is the only runtime dependency, and only the YAML layer uses it: every range computation
stays on the standard library's ``ipaddress``.

Two things are still refused rather than accepted, because both mean the file on disk is not the
file the author thinks it is: a stream holding more than one document, and a duplicate mapping
key (what ``cat a.yaml b.yaml`` produces). A merge key (``<<: *defaults``) is refused too: the
composer leaves it as an ordinary ``<<`` entry, so merging it would be our own invention, and
ignoring it would drop whatever the merged mapping carried.

Anchors and aliases *are* resolved by the composer, which hands the *same* node back for every
alias to it. Converting that node once per alias is what makes an expansion bomb ("billion
laughs") exponential, so every node is converted once and memoised by ``id``, and the size its
aliases expand to is capped -- see :data:`MAX_NODES`.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from ..errors import InputError

#: Ceiling on the number of nodes a document expands to once its aliases are followed. A netplan
#: file of any realistic size is three orders of magnitude below this; only a bomb reaches it.
MAX_NODES = 100_000

MULTI_DOC = "multiple YAML documents are not supported"
TOO_LARGE = f"YAML expands to more than {MAX_NODES} nodes once aliases are resolved"
RECURSIVE = "recursive YAML anchor"
MERGE = "YAML merge keys ('<<') are not supported"

#: Tag PyYAML resolves ``eth0:``, ``~`` and ``null`` to.
NULL_TAG = "tag:yaml.org,2002:null"
#: Tag PyYAML gives the ``<<`` key.
MERGE_TAG = "tag:yaml.org,2002:merge"


@dataclass(frozen=True)
class Scalar:
    line: int
    value: str
    #: True for a key written with no value at all (``eth0:``), ``~`` or ``null``.
    null: bool = False


@dataclass(frozen=True)
class Mapping:
    line: int
    items: dict[str, Node]


@dataclass(frozen=True)
class Sequence:
    line: int
    items: list[Node]


Node = Scalar | Mapping | Sequence


def _line(node: yaml.Node) -> int:
    return node.start_mark.line + 1


def _at(node: yaml.Node, filename: str) -> str:
    return f"{filename}:{_line(node)}"


def _convert(
    node: yaml.Node,
    filename: str,
    seen: frozenset[int],
    cache: dict[int, tuple[Node, int]],
) -> tuple[Node, int]:
    """Turn one composer node into ours, with the number of nodes it expands to.

    ``cache`` holds every node already converted, keyed by ``id``. The composer gives the same
    node object back for every alias to an anchor, so without that cache a document like
    ``&a [x, x]`` / ``&b [*a, *a]`` / ``&c [*b, *b]`` would be walked 2**depth times -- the
    billion-laughs expansion. Converting each node once makes the cost linear in the nodes that
    are actually written, and the returned weight (what the tree expands to once aliases are
    followed, which is what the readers walk) is capped at :data:`MAX_NODES`.

    ``seen`` holds the collection nodes on the path to here, so a recursive anchor
    (``&loop [*loop]``) is refused instead of recursing forever. Two *sibling* aliases to the
    same node are fine: the first converts it, the second gets the cached result.
    """
    cached = cache.get(id(node))
    if cached is not None:
        return cached

    if isinstance(node, yaml.ScalarNode):
        scalar = (
            Scalar(_line(node), "", null=True)
            if node.tag == NULL_TAG
            else Scalar(_line(node), node.value)
        )
        cache[id(node)] = (scalar, 1)
        return scalar, 1

    if id(node) in seen:
        raise InputError(RECURSIVE, _at(node, filename))
    inner = seen | {id(node)}
    weight = 1
    converted: Node

    if isinstance(node, yaml.SequenceNode):
        items: list[Node] = []
        for item in node.value:
            child, child_weight = _convert(item, filename, inner, cache)
            items.append(child)
            weight += child_weight
            if weight > MAX_NODES:
                raise InputError(TOO_LARGE, _at(node, filename))
        converted = Sequence(_line(node), items)
    elif isinstance(node, yaml.MappingNode):
        pairs: dict[str, Node] = {}
        for key_node, value_node in node.value:
            if not isinstance(key_node, yaml.ScalarNode):
                raise InputError("mapping key must be a plain value", _at(key_node, filename))
            if key_node.tag == MERGE_TAG:
                raise InputError(MERGE, _at(key_node, filename))
            key = key_node.value
            if key in pairs:
                raise InputError(f"duplicate key {key!r}", _at(key_node, filename))
            child, child_weight = _convert(value_node, filename, inner, cache)
            pairs[key] = child
            weight += 1 + child_weight
            if weight > MAX_NODES:
                raise InputError(TOO_LARGE, _at(node, filename))
        converted = Mapping(_line(node), pairs)
    else:
        raise InputError(f"unsupported YAML node {node.tag}", _at(node, filename))

    cache[id(node)] = (converted, weight)
    return converted, weight


def _describe(exc: yaml.YAMLError) -> str:
    """PyYAML's own diagnosis, which is more precise than anything we would write."""
    parts = [
        str(part) for part in (getattr(exc, "context", None), getattr(exc, "problem", None)) if part
    ]
    return f"invalid YAML: {': '.join(parts)}" if parts else f"invalid YAML: {exc}"


def _where(exc: yaml.YAMLError, filename: str) -> str:
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    return f"{filename}:{mark.line + 1}" if mark is not None else filename


def parse(text: str, filename: str) -> Node | None:
    """Parse a netplan YAML document. Returns ``None`` for an empty file."""
    try:
        documents = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as exc:
        # Content after a `...` end marker never even reaches compose_all as a second document:
        # the parser stops at the token that would have to open one.
        if "document start" in str(getattr(exc, "problem", "") or ""):
            raise InputError(MULTI_DOC, _where(exc, filename)) from exc
        raise InputError(_describe(exc), _where(exc, filename)) from exc

    if len(documents) > 1:
        second = documents[1]
        where = _at(second, filename) if second is not None else filename
        raise InputError(MULTI_DOC, where)
    if not documents or documents[0] is None:
        return None
    return _convert(documents[0], filename, frozenset(), {})[0]
