"""Unit tests for :func:`src.search.extract_snippet` and the CLI integration.

The fixtures use :class:`src.indexer.Indexer` to build the index so that the
tokenisation rules and position numbering match the production pipeline
exactly. This means a snippet test that passes here also reflects the
behaviour a user would see at the ``find`` prompt.
"""

from __future__ import annotations

import io
import sys

import pytest

from src.indexer import Indexer, InvertedIndex
from src.main import Shell
from src.search import (
    extract_snippet,
    query_positive_terms,
    reconstruct_tokens,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def long_index() -> InvertedIndex:
    """A single-document index with predictable token positions.

    The body has 30 tokens; ``love`` is at position 0, ``life`` is at
    position 29 (last), and ``truth`` appears twice in the middle.
    """
    body = (
        "love story chapter one - the morning was bright and the "
        "wind moved softly truth and beauty walked on through truth "
        "again every gentle minute carried life"
    )
    pages = {"http://a/": f"<p>{body}</p>"}
    return Indexer().build_index(pages)


@pytest.fixture
def small_corpus() -> InvertedIndex:
    """Two short pages so the CLI tests can exercise multi-result output."""
    pages = {
        "http://a/": "<p>good day good night friends</p>",
        "http://b/": "<p>bad night friends</p>",
    }
    return Indexer().build_index(pages)


# --------------------------------------------------------------------------- #
# reconstruct_tokens                                                          #
# --------------------------------------------------------------------------- #


def test_reconstruct_tokens_recovers_original_order(long_index):
    tokens = reconstruct_tokens(long_index, "http://a/")
    assert tokens[0] == "love"
    assert tokens[-1] == "life"
    assert tokens.count("truth") == 2


def test_reconstruct_tokens_unknown_url_returns_empty(long_index):
    assert reconstruct_tokens(long_index, "http://missing/") == []


# --------------------------------------------------------------------------- #
# extract_snippet — match position cases                                      #
# --------------------------------------------------------------------------- #


def test_snippet_match_at_start_has_no_left_ellipsis(long_index):
    snippet = extract_snippet(long_index, "http://a/", ["love"])
    # Query word is the first token, so there is nothing to the left.
    assert snippet.startswith("**love**")
    assert " ..." in snippet  # right-truncated because window stops short


def test_snippet_match_at_end_has_no_right_ellipsis(long_index):
    snippet = extract_snippet(long_index, "http://a/", ["life"])
    # Query word is the last token, so the right side is not truncated.
    assert snippet.endswith("**life**")
    assert snippet.startswith("...")


def test_snippet_window_is_eight_tokens_each_side(long_index):
    snippet = extract_snippet(long_index, "http://a/", ["love"], window=8)
    # 8 tokens to the right of love + love itself = 9 tokens, then truncated.
    visible_words = [w.strip("*") for w in snippet.split() if w != "..."]
    assert len(visible_words) <= 9


def test_snippet_overlapping_multi_term_matches_all_get_marked(long_index):
    snippet = extract_snippet(long_index, "http://a/", ["truth", "beauty"])
    # 'truth' (twice) and 'beauty' are all close together; all should be bold.
    assert snippet.count("**truth**") == 2
    assert "**beauty**" in snippet


def test_snippet_uses_first_match_as_anchor(long_index):
    snippet = extract_snippet(long_index, "http://a/", ["truth"])
    # First 'truth' is at position 14; window is +-8, so 'love' at 0 must
    # *not* appear and 'life' at 29 must *not* appear.
    assert "love" not in snippet
    assert "life" not in snippet


# --------------------------------------------------------------------------- #
# extract_snippet — formatting cases                                          #
# --------------------------------------------------------------------------- #


def test_snippet_ansi_mode_emits_escape_codes(long_index):
    snippet = extract_snippet(
        long_index, "http://a/", ["truth"], ansi=True
    )
    assert "\x1b[1m" in snippet
    assert "\x1b[22m" in snippet
    assert "**" not in snippet


def test_snippet_markdown_mode_uses_double_asterisks(long_index):
    snippet = extract_snippet(long_index, "http://a/", ["truth"])
    assert "\x1b[" not in snippet
    assert "**truth**" in snippet


def test_snippet_empty_query_returns_empty_string(long_index):
    assert extract_snippet(long_index, "http://a/", []) == ""


def test_snippet_query_terms_with_only_blanks_returns_empty(long_index):
    assert extract_snippet(long_index, "http://a/", [""]) == ""


def test_snippet_no_match_returns_empty_string(long_index):
    assert extract_snippet(long_index, "http://a/", ["mongoose"]) == ""


def test_snippet_unknown_url_returns_empty_string(long_index):
    assert extract_snippet(long_index, "http://missing/", ["love"]) == ""


# --------------------------------------------------------------------------- #
# query_positive_terms                                                        #
# --------------------------------------------------------------------------- #


def test_query_positive_terms_flattens_phrase_and_positives():
    terms = query_positive_terms('good "good night" friends')
    assert "good" in terms
    assert "night" in terms
    assert "friends" in terms


def test_query_positive_terms_ignores_negatives():
    terms = query_positive_terms("good NOT bad")
    assert "good" in terms
    assert "bad" not in terms


# --------------------------------------------------------------------------- #
# CLI integration                                                             #
# --------------------------------------------------------------------------- #


def test_cmd_find_prints_snippet_under_each_result(
    small_corpus, capsys, monkeypatch
):
    """The CLI should call extract_snippet for every result line.

    We force ``sys.stdout.isatty`` to ``False`` so the output uses the
    deterministic ``**term**`` markdown markers regardless of the test
    environment.
    """
    shell = Shell()
    shell.index = small_corpus
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)

    shell.cmd_find(["good"])
    captured = capsys.readouterr().out
    # Every result URL should be followed by a snippet line containing **good**.
    assert "**good**" in captured
    assert "http://a/" in captured


def test_cmd_find_uses_ansi_when_stdout_is_a_tty(
    small_corpus, capsys, monkeypatch
):
    shell = Shell()
    shell.index = small_corpus
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)

    shell.cmd_find(["good"])
    captured = capsys.readouterr().out
    assert "\x1b[1m" in captured
    assert "\x1b[22m" in captured
