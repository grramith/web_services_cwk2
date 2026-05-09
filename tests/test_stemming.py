"""Tests for the optional Porter-stemmer code-paths added in T8.

The default behaviour (stemming OFF) is already exercised across the rest
of the test suite — these tests focus on the stem=ON branches so each new
parameter has explicit positive and negative coverage. The CLI tests run
through :class:`src.main.Shell` rather than reaching into helpers, so the
end-to-end build / load / find flow is verified against a real
:func:`save_index` / :func:`load_index_metadata` round-trip.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from src.indexer import Indexer, tokenize
from src.main import Shell
from src.search import find, find_with_suggestions, parse_query
from src.storage import (
    load_index,
    load_index_metadata,
    save_index,
)


# --------------------------------------------------------------------------- #
# tokenize                                                                    #
# --------------------------------------------------------------------------- #


def test_tokenize_stem_off_preserves_morphology():
    assert tokenize("running runs ran") == ["running", "runs", "ran"]


def test_tokenize_stem_on_collapses_morphology():
    assert tokenize("running runs", stem=True) == ["run", "run"]


def test_tokenize_stem_on_handles_empty_input():
    assert tokenize("", stem=True) == []


# --------------------------------------------------------------------------- #
# Indexer + search                                                            #
# --------------------------------------------------------------------------- #


def test_indexer_stem_merges_morphological_variants():
    pages = {
        "http://a/": "<p>I am running every morning</p>",
        "http://b/": "<p>She runs each evening</p>",
    }
    index = Indexer(stem=True).build_index(pages)

    assert "run" in index
    # Both morphological variants land in the same posting.
    assert set(index["run"].keys()) == {"http://a/", "http://b/"}
    # The unstemmed forms should not appear as separate keys.
    assert "running" not in index
    assert "runs" not in index


def test_find_with_stem_matches_morphological_variant():
    pages = {
        "http://a/": "<p>The dog runs across the field</p>",
        "http://b/": "<p>An apple a day</p>",
    }
    index = Indexer(stem=True).build_index(pages)
    # Query says 'running' but the index only has 'runs' — both stem to
    # 'run', so the match must succeed.
    assert find(index, "running", stem=True) == ["http://a/"]


def test_parse_query_stem_on_stems_positives_and_phrases():
    groups = parse_query('running "ran fast"', stem=True)
    assert groups[0].positives == ["run"]
    assert groups[0].phrases == [["ran", "fast"]]


def test_parse_query_stem_off_leaves_morphology_intact():
    groups = parse_query("running")
    assert groups[0].positives == ["running"]


def test_find_with_suggestions_stem_path_returns_results():
    pages = {"http://a/": "<p>running and jumping</p>"}
    index = Indexer(stem=True).build_index(pages)
    results, suggestions = find_with_suggestions(index, "runs", stem=True)
    assert results == ["http://a/"]
    assert suggestions == []


# --------------------------------------------------------------------------- #
# Storage metadata round-trip                                                 #
# --------------------------------------------------------------------------- #


def test_save_index_writes_metadata_sidecar(tmp_path):
    path = tmp_path / "idx.json"
    save_index({"hello": {"http://a/": {"frequency": 1, "positions": [0]}}},
               str(path), stem=True)
    meta = load_index_metadata(str(path))
    assert meta["stem"] is True


def test_save_index_default_metadata_marks_stem_off(tmp_path):
    path = tmp_path / "idx.json"
    save_index({}, str(path))
    meta = load_index_metadata(str(path))
    assert meta["stem"] is False


def test_load_index_metadata_missing_sidecar_returns_default(tmp_path):
    # Create only the index file; no sidecar.
    path = tmp_path / "idx.json"
    path.write_text("{}")
    meta = load_index_metadata(str(path))
    assert meta == {"stem": False}


def test_load_index_metadata_invalid_json_returns_default(tmp_path):
    path = tmp_path / "idx.json"
    path.write_text("{}")
    sidecar = tmp_path / "idx.json.meta.json"
    sidecar.write_text("{ this is not valid")
    meta = load_index_metadata(str(path))
    assert meta == {"stem": False}


def test_load_index_metadata_unknown_keys_passed_through(tmp_path):
    path = tmp_path / "idx.json"
    path.write_text("{}")
    sidecar = tmp_path / "idx.json.meta.json"
    sidecar.write_text(json.dumps({"stem": True, "future_flag": "x"}))
    meta = load_index_metadata(str(path))
    assert meta["stem"] is True
    assert meta["future_flag"] == "x"


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def test_cmd_build_stem_flag_persists_metadata(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(tmp_path / "idx.json")
    shell = Shell(index_path=path)
    fake_pages = {"http://quotes.toscrape.com/": "<p>I am running</p>"}
    with patch("src.main.Crawler") as crawler_cls:
        crawler_cls.return_value.crawl.return_value = fake_pages
        shell.dispatch("build --stem")

    out = capsys.readouterr().out
    assert "Porter stemmer ON" in out
    assert shell.stem is True
    assert os.path.exists(path)
    assert os.path.exists(path + ".meta.json")
    # 'running' should have been stemmed to 'run' in the persisted index.
    saved = load_index(path)
    assert "run" in saved
    assert "running" not in saved


def test_cmd_load_picks_up_stem_metadata(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(tmp_path / "idx.json")
    save_index(
        {"run": {"http://a/": {"frequency": 1, "positions": [0]}}},
        path,
        stem=True,
    )
    shell = Shell(index_path=path)
    shell.dispatch("load")
    out = capsys.readouterr().out
    assert "Porter stemmer ON" in out
    assert shell.stem is True


def test_cmd_find_uses_self_stem_for_query_tokens(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = str(tmp_path / "idx.json")
    pages = {"http://a/": "<p>running fast</p>"}
    index = Indexer(stem=True).build_index(pages)
    save_index(index, path, stem=True)

    shell = Shell(index_path=path)
    shell.dispatch("load")
    capsys.readouterr()  # discard load message
    shell.dispatch("find runs")
    out = capsys.readouterr().out
    assert "http://a/" in out


def test_cmd_build_rejects_invalid_max_pages_with_stem_flag(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    shell = Shell(index_path=str(tmp_path / "idx.json"))
    shell.dispatch("build seven --stem")
    out = capsys.readouterr().out
    assert "Usage:" in out
    assert shell.index is None
