from __future__ import annotations

from pathlib import Path

import pytest

from subnet_clash.model import RangeEntry
from subnet_clash.sources import get_reader

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_path(name: str) -> str:
    return str(FIXTURES / name)


def read_fixture(source_type: str, name: str) -> list[RangeEntry]:
    """Parse a fixture, keeping the bare file name in locations so assertions stay readable."""
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return get_reader(source_type)(text, name)


@pytest.fixture
def load():
    return read_fixture
