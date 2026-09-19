"""Errors that map to the CLI's exit code 2 (bad input)."""

from __future__ import annotations


class SubnetClashError(Exception):
    """Base class for every error that means "your input is not usable"."""


class InputError(SubnetClashError):
    """A source file is missing, unreadable, malformed, or holds an unusable value.

    ``location`` is a ``file`` or ``file:line`` string when we know where the problem is.
    """

    def __init__(self, message: str, location: str | None = None) -> None:
        self.message = message
        self.location = location
        super().__init__(f"{location}: {message}" if location else message)
