"""Unit tests for :mod:`src.storage`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.storage import IndexNotFoundError, load_index, save_index


SAMPLE_INDEX = {
    "good": {
        "http://example.com/a": {"frequency": 2, "positions": [0, 5]},
        "http://example.com/b": {"frequency": 1, "positions": [3]},
    },
    "day": {
        "http://example.com/a": {"frequency": 1, "positions": [1]},
    },
}


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    """save_index → load_index must yield an equal dict."""
    path = tmp_path / "index.json"
    save_index(SAMPLE_INDEX, str(path))
    loaded = load_index(str(path))

    assert loaded == SAMPLE_INDEX


def test_load_missing_file_raises_index_not_found(tmp_path: Path) -> None:
    """Loading a non-existent path must raise the custom exception."""
    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(IndexNotFoundError):
        load_index(str(missing))


def test_index_not_found_is_a_file_not_found_subclass() -> None:
    """The custom exception must remain catchable as ``FileNotFoundError``."""
    assert issubclass(IndexNotFoundError, FileNotFoundError)


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    """Saving to a nested path that doesn't exist yet must auto-create it."""
    nested = tmp_path / "a" / "b" / "c" / "index.json"
    save_index(SAMPLE_INDEX, str(nested))

    assert nested.is_file()
    assert json.loads(nested.read_text(encoding="utf-8")) == SAMPLE_INDEX


def test_save_writes_human_readable_json(tmp_path: Path) -> None:
    """The on-disk format must be pretty-printed JSON, not minified."""
    path = tmp_path / "index.json"
    save_index(SAMPLE_INDEX, str(path))
    raw = path.read_text(encoding="utf-8")

    assert "\n" in raw
    assert "  " in raw  # two-space indent


def test_load_invalid_json_raises_value_error(tmp_path: Path) -> None:
    """A corrupt JSON file must raise ``ValueError`` with a clear message."""
    path = tmp_path / "broken.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError):
        load_index(str(path))


def test_save_and_load_handles_unicode(tmp_path: Path) -> None:
    """Non-ASCII tokens (smart quotes, accented chars) must round-trip cleanly."""
    index = {
        "café": {"http://x/": {"frequency": 1, "positions": [0]}},
        "naïve": {"http://x/": {"frequency": 1, "positions": [1]}},
    }
    path = tmp_path / "unicode.json"
    save_index(index, str(path))

    assert load_index(str(path)) == index
