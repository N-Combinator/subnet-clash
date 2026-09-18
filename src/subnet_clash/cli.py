"""Command line entry point.

Exit codes: ``0`` clean, ``1`` at least one clash, ``2`` unusable input.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .analyze import analyze
from .errors import SubnetClashError
from .model import RangeEntry
from .report import defaults_to_json, defaults_to_markdown, to_json, to_markdown
from .sources import get_reader, read_source

EXIT_OK = 0
EXIT_CLASH = 1
EXIT_INPUT_ERROR = 2

#: CLI flag -> source type. Every value is a file path; ``-`` means stdin.
SOURCE_FLAGS = (
    ("--wg", "wireguard", "WireGuard config (AllowedIPs, Address)"),
    ("--docker", "docker", "saved `docker network inspect` JSON"),
    ("--netplan", "netplan", "netplan YAML"),
    ("--nm", "networkmanager", "NetworkManager keyfile (*.nmconnection)"),
    ("--dnsmasq", "dnsmasq", "dnsmasq config (dhcp-range)"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subnet-clash",
        description=(
            "Find overlapping IP ranges across the network configs you already have. "
            "Reads files only - it never inspects the live system."
        ),
    )
    parser.add_argument("--version", action="version", version=f"subnet-clash {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="compare ranges across config files")
    for flag, source_type, help_text in SOURCE_FLAGS:
        check.add_argument(
            flag,
            dest=source_type,
            metavar="FILE",
            action="append",
            default=[],
            help=f"{help_text}; repeatable, '-' reads stdin",
        )
    check.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="report format",
    )
    check.add_argument(
        "-o", "--output", metavar="FILE", help="write the report here instead of stdout"
    )
    check.add_argument(
        "--include-default-routes",
        action="store_true",
        help="also compare 0.0.0.0/0 and ::/0 (they collide with everything)",
    )
    check.add_argument(
        "--no-default-check",
        action="store_true",
        help="skip the well-known-default-range warnings",
    )

    defaults = subparsers.add_parser(
        "defaults", help="print the table of well-known default ranges with sources"
    )
    defaults.add_argument("--format", choices=("markdown", "json"), default="markdown")

    return parser


def _collect(args: argparse.Namespace) -> tuple[list[RangeEntry], list[dict[str, object]]]:
    entries: list[RangeEntry] = []
    sources: list[dict[str, object]] = []
    paths = [
        (source_type, path)
        for _flag, source_type, _help in SOURCE_FLAGS
        for path in getattr(args, source_type)
    ]
    if sum(1 for _type, path in paths if path == "-") > 1:
        raise SubnetClashError("stdin ('-') can only be used for one source")
    for source_type, path in paths:
        display, text = read_source(path)
        found = get_reader(source_type)(text, display)
        if not found:
            # Every silent half-read found so far looked exactly like this: a file that parsed
            # without complaint and yielded nothing. Say so on stderr; it is not an error, an
            # empty config is legal, but it should never pass unnoticed.
            print(
                f"subnet-clash: warning: {display}: read as {source_type}, no ranges found",
                file=sys.stderr,
            )
        entries.extend(found)
        sources.append({"file": display, "type": source_type, "ranges": len(found)})
    return entries, sources


def _write(text: str, output: str | None) -> None:
    if output is None:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        return
    try:
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(text if text.endswith("\n") else text + "\n")
    except OSError as exc:
        raise SubnetClashError(f"cannot write {output}: {exc.strerror}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "defaults":
            _write(defaults_to_json() if args.format == "json" else defaults_to_markdown(), None)
            return EXIT_OK

        entries, sources = _collect(args)
        if not sources:
            raise SubnetClashError(
                "no source files given; pass at least one of "
                + ", ".join(flag for flag, _t, _h in SOURCE_FLAGS)
            )
        report = analyze(
            entries,
            include_default_routes=args.include_default_routes,
            check_defaults=not args.no_default_check,
        )
        rendered = (
            to_json(report, sources) if args.format == "json" else to_markdown(report, sources)
        )
        _write(rendered, args.output)
        return EXIT_CLASH if report.clashes else EXIT_OK
    except SubnetClashError as exc:
        print(f"subnet-clash: error: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except BrokenPipeError:  # pragma: no cover - depends on the consumer
        return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
