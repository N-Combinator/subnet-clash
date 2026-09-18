"""A deliberately small YAML-subset reader that remembers line numbers.

v0.1 ships with the standard library only, so there is no PyYAML. netplan files use a narrow
dialect -- nested block mappings, block sequences, flow sequences, plain scalars -- and that is
exactly what this module understands. Anything outside that subset raises
:class:`~subnet_clash.errors.InputError`, so the CLI fails loudly (exit 2) instead of silently
reading half a file.

Not supported, and rejected: anchors/aliases, multi-line block scalars, multiple documents,
duplicate keys, tab indentation. Flow mappings are the one thing kept as opaque scalar text.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import InputError

MULTI_DOC = "multiple YAML documents are not supported"
ANCHOR = "YAML anchors and aliases are not supported"


@dataclass(frozen=True)
class Scalar:
    line: int
    value: str


@dataclass(frozen=True)
class Mapping:
    line: int
    items: dict[str, Node]


@dataclass(frozen=True)
class Sequence:
    line: int
    items: list[Node]


Node = Scalar | Mapping | Sequence


@dataclass(frozen=True)
class _Line:
    lineno: int
    indent: int
    content: str
    is_item: bool
    item_col: int


def _strip_comment(raw: str) -> str:
    quote: str | None = None
    for i, ch in enumerate(raw):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i]
    return raw


def _mkline(lineno: int, indent: int, content: str) -> _Line:
    is_item = content == "-" or content.startswith("- ")
    if is_item:
        rest = content[1:]
        item_col = indent + 1 + (len(rest) - len(rest.lstrip(" ")))
    else:
        item_col = indent
    return _Line(lineno, indent, content, is_item, item_col)


def _tokenize(text: str, filename: str) -> list[_Line]:
    """Split the text into meaningful lines, rejecting anything but a single document.

    A file may open with ``---`` and close with ``...``, but a second document -- another
    ``---``, or content after the ``...`` -- is refused. Reading only one document out of
    several is exactly the silent half-read this reader exists to avoid.
    """
    lines: list[_Line] = []
    started = False
    ended = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        body = _strip_comment(raw).rstrip()
        if not body.strip():
            continue
        marker = body.strip()
        if marker == "---":
            if started or ended:
                raise InputError(MULTI_DOC, f"{filename}:{lineno}")
            started = True
            continue
        if marker == "...":
            if ended:
                raise InputError(MULTI_DOC, f"{filename}:{lineno}")
            ended = True
            continue
        if ended:
            raise InputError(MULTI_DOC, f"{filename}:{lineno}")
        started = True
        prefix = body[: len(body) - len(body.lstrip(" \t"))]
        if "\t" in prefix:
            raise InputError("tab used for indentation (YAML forbids it)", f"{filename}:{lineno}")
        stripped = body[len(prefix) :]
        indent = len(prefix)
        lines.append(_mkline(lineno, indent, stripped))
    return lines


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _split_key(content: str) -> tuple[str, str] | None:
    """Split ``key: value`` on the first structural colon. ``None`` when there is no key."""
    quote: str | None = None
    for i, ch in enumerate(content):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in "[{":
            return None
        elif ch == ":" and (i + 1 == len(content) or content[i + 1] == " "):
            return _unquote(content[:i]), content[i + 1 :].strip()
    return None


def _split_flow(body: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for ch in body:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            current.append(ch)
        elif ch == ",":
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p for p in (p.strip() for p in parts) if p]


def _scalar(value: str, lineno: int, filename: str) -> Scalar:
    """Build a scalar, refusing an anchor definition (``&lan``) or an alias (``*lan``).

    Resolving them would mean implementing a second half of YAML; treating them as ordinary text
    is worse, because ``addresses: *lan`` then reads as zero addresses and the file looks clean.
    """
    if value.startswith(("&", "*")):
        raise InputError(ANCHOR, f"{filename}:{lineno}")
    return Scalar(lineno, _unquote(value))


def _inline(value: str, lineno: int, filename: str) -> Node:
    if value.startswith("[") and value.endswith("]"):
        return Sequence(lineno, [_scalar(p, lineno, filename) for p in _split_flow(value[1:-1])])
    return _scalar(value, lineno, filename)


def _parse_block(
    lines: list[_Line], pos: int, indent: int, filename: str, *, allow_scalar: bool = False
) -> tuple[Node, int]:
    head = lines[pos]
    if head.is_item:
        return _parse_sequence(lines, pos, indent, filename)
    if _split_key(head.content) is None:
        if not allow_scalar:
            raise InputError(
                f"expected 'key: value', got {head.content!r}", f"{filename}:{head.lineno}"
            )
        return _scalar(head.content, head.lineno, filename), pos + 1
    return _parse_mapping(lines, pos, indent, filename)


def _parse_mapping(lines: list[_Line], pos: int, indent: int, filename: str) -> tuple[Node, int]:
    items: dict[str, Node] = {}
    line0 = lines[pos].lineno
    while pos < len(lines) and lines[pos].indent == indent and not lines[pos].is_item:
        line = lines[pos]
        split = _split_key(line.content)
        if split is None:
            raise InputError(
                f"expected 'key: value', got {line.content!r}", f"{filename}:{line.lineno}"
            )
        key, value = split
        if key in items:
            raise InputError(f"duplicate key {key!r}", f"{filename}:{line.lineno}")
        if value:
            items[key] = _inline(value, line.lineno, filename)
            pos += 1
            continue
        nxt = lines[pos + 1] if pos + 1 < len(lines) else None
        if nxt is not None and (nxt.indent > indent or (nxt.indent == indent and nxt.is_item)):
            items[key], pos = _parse_block(lines, pos + 1, nxt.indent, filename)
        else:
            items[key] = Scalar(line.lineno, "")
            pos += 1
    return Mapping(line0, items), pos


def _parse_sequence(lines: list[_Line], pos: int, indent: int, filename: str) -> tuple[Node, int]:
    items: list[Node] = []
    line0 = lines[pos].lineno
    while pos < len(lines) and lines[pos].indent == indent and lines[pos].is_item:
        head = lines[pos]
        rest = head.content[1:].strip()
        sub: list[_Line] = []
        if rest:
            sub.append(_mkline(head.lineno, head.item_col, rest))
        end = pos + 1
        while end < len(lines) and lines[end].indent > head.indent:
            sub.append(lines[end])
            end += 1
        if not sub:
            raise InputError("empty list item", f"{filename}:{head.lineno}")
        node, _ = _parse_block(sub, 0, sub[0].indent, filename, allow_scalar=True)
        items.append(node)
        pos = end
    return Sequence(line0, items), pos


def parse(text: str, filename: str) -> Node | None:
    """Parse a netplan-flavoured YAML document. Returns ``None`` for an empty file."""
    lines = _tokenize(text, filename)
    if not lines:
        return None
    node, pos = _parse_block(lines, 0, lines[0].indent, filename)
    if pos != len(lines):
        leftover = lines[pos]
        raise InputError(
            f"unexpected indentation at {leftover.content!r}", f"{filename}:{leftover.lineno}"
        )
    return node
