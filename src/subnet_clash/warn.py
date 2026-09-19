"""The one place a non-fatal message reaches the user.

A warning is for something the tool read but could not turn into a comparable range, or read in a
way the author may not have meant. It goes to stderr, so a report written to stdout stays machine
readable, and it never changes the exit code.
"""

from __future__ import annotations

import sys


def warn(message: str, location: str | None = None) -> None:
    where = f"{location}: " if location else ""
    print(f"subnet-clash: warning: {where}{message}", file=sys.stderr)
