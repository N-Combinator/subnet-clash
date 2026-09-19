"""Render a :class:`~subnet_clash.model.Report` as JSON or Markdown."""

from __future__ import annotations

import json
from collections import Counter

from . import __version__
from .defaults import DEFAULT_RANGES
from .model import Report

KIND_ORDER = ("overlap", "identical", "contains")

KIND_BLURB = {
    "overlap": (
        "partial overlap - each side also owns addresses the other does not; almost always a bug"
    ),
    "identical": "the two ranges are exactly the same block",
    "contains": (
        "one range sits entirely inside the other - frequently deliberate "
        "(a DHCP pool inside its LAN, a peer inside a tunnel subnet)"
    ),
}


def _summary(report: Report) -> dict[str, int]:
    counts = Counter(clash.kind for clash in report.clashes)
    return {
        "ranges": len(report.entries),
        "clashes": len(report.clashes),
        "overlap": counts.get("overlap", 0),
        "identical": counts.get("identical", 0),
        "contains": counts.get("contains", 0),
        "default_range_warnings": len(report.warnings),
        "skipped_default_routes": len(report.skipped_default_routes),
        "undetermined": len(report.undetermined),
    }


def _sorted_clashes(report: Report) -> list:
    return sorted(
        report.clashes,
        key=lambda c: (
            KIND_ORDER.index(c.kind),
            c.a.location.file,
            c.a.location.line or 0,
            c.b.location.file,
            c.b.location.line or 0,
        ),
    )


def to_json(report: Report, sources: list[dict[str, object]]) -> str:
    payload = {
        "tool": "subnet-clash",
        "version": __version__,
        "sources": sources,
        "summary": _summary(report),
        "ranges": [entry.as_dict() for entry in report.entries],
        "clashes": [clash.as_dict() for clash in _sorted_clashes(report)],
        "default_range_warnings": [warning.as_dict() for warning in report.warnings],
        "skipped_default_routes": [entry.as_dict() for entry in report.skipped_default_routes],
        "undetermined_ranges": [entry.as_dict() for entry in report.undetermined],
    }
    return json.dumps(payload, indent=2, sort_keys=False)


def _side(label: str, entry) -> str:
    key = f" (`{entry.location.key}`)" if entry.location.key else ""
    return f"- **{label}** `{entry.raw}` - {entry.name} - `{entry.location}`{key}"


def to_markdown(report: Report, sources: list[dict[str, object]]) -> str:
    summary = _summary(report)
    out: list[str] = ["# subnet-clash report", ""]

    out.append("## Sources")
    out.append("")
    out.append("| file | type | ranges |")
    out.append("| --- | --- | --- |")
    for source in sources:
        out.append(f"| `{source['file']}` | {source['type']} | {source['ranges']} |")
    out.append("")

    out.append(
        f"**{summary['clashes']} clash(es)** across {summary['ranges']} range(s): "
        f"{summary['overlap']} overlap, {summary['identical']} identical, "
        f"{summary['contains']} contains."
    )
    out.append("")

    if report.clashes:
        out.append("## Clashes")
        out.append("")
        for index, clash in enumerate(_sorted_clashes(report), start=1):
            out.append(f"### {index}. {clash.kind}: `{clash.a.location}` vs `{clash.b.location}`")
            out.append("")
            out.append(_side("A", clash.a))
            out.append(_side("B", clash.b))
            shared = ", ".join(f"`{n}`" for n in clash.intersection)
            out.append(f"- shared: {shared}")
            if clash.kind == "contains":
                outer, inner = ("A", "B") if clash.container == "a" else ("B", "A")
                out.append(f"- {inner} is fully inside {outer}")
            out.append(f"- {KIND_BLURB[clash.kind]}")
            out.append("")
    else:
        out.append("No clashes found.")
        out.append("")

    if report.warnings:
        out.append("## Well-known default ranges in use")
        out.append("")
        out.append("| range | where | relation | default range | source |")
        out.append("| --- | --- | --- | --- | --- |")
        for warning in report.warnings:
            out.append(
                f"| `{warning.entry.raw}` | `{warning.entry.location}` | {warning.relation} "
                f"| `{warning.default_network}` - {warning.default_name} "
                f"| {warning.default_source} |"
            )
        out.append("")

    if report.undetermined:
        out.append("## Undetermined ranges")
        out.append("")
        out.append(
            "These lines declare a range whose size is not written in the file, so they were "
            "not compared with anything."
        )
        out.append("")
        for entry in report.undetermined:
            out.append(
                f"- `{entry.raw}` - {entry.name} - `{entry.location}` - {entry.undetermined}"
            )
        out.append("")

    if report.skipped_default_routes:
        out.append("## Skipped default routes")
        out.append("")
        out.append(
            "These cover the whole address space and would collide with everything; "
            "pass `--include-default-routes` to compare them anyway."
        )
        out.append("")
        for entry in report.skipped_default_routes:
            out.append(f"- `{entry.raw}` - {entry.name} - `{entry.location}`")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def defaults_to_markdown() -> str:
    out = [
        "# Well-known default ranges",
        "",
        "Every row carries the document it came from; "
        "a range without a citable source is not listed.",
        "",
        "| range | kind | what uses it | source |",
        "| --- | --- | --- | --- |",
    ]
    for default in DEFAULT_RANGES:
        out.append(f"| `{default.network}` | {default.kind} | {default.name} | {default.source} |")
    return "\n".join(out) + "\n"


def defaults_to_json() -> str:
    return json.dumps(
        {
            "tool": "subnet-clash",
            "version": __version__,
            "default_ranges": [
                {
                    "network": str(default.network),
                    "kind": default.kind,
                    "name": default.name,
                    "source": default.source,
                }
                for default in DEFAULT_RANGES
            ],
        },
        indent=2,
    )
