"""Unit tests for :mod:`src.search`."""

from __future__ import annotations

import pytest

from src.indexer import Indexer, InvertedIndex
from src.search import find, has_phrase, parse_query, print_word


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def small_index() -> InvertedIndex:
    """A tiny, hand-checked corpus used across most tests in this module."""
    pages = {
        "http://a/": "<p>good day good night</p>",
        "http://b/": "<p>good morning friends</p>",
        "http://c/": "<p>bad night friends friends</p>",
    }
    return Indexer().build_index(pages)


# --------------------------------------------------------------------------- #
# print_word                                                                  #
# --------------------------------------------------------------------------- #


def test_print_word_existing_outputs_url_freq_positions(
    small_index: InvertedIndex, capsys: pytest.CaptureFixture[str]
) -> None:
    """Printing an existing term must show URL, frequency, and positions."""
    print_word(small_index, "good")
    out = capsys.readouterr().out

    assert "http://a/" in out
    assert "frequency: 2" in out
    assert "[0, 2]" in out
    assert "http://b/" in out


def test_print_word_missing_outputs_friendly_message(
    small_index: InvertedIndex, capsys: pytest.CaptureFixture[str]
) -> None:
    """Printing a missing term must not crash; it should say so plainly."""
    print_word(small_index, "nonexistent")
    out = capsys.readouterr().out

    assert "not in the index" in out


def test_print_word_is_case_insensitive(
    small_index: InvertedIndex, capsys: pytest.CaptureFixture[str]
) -> None:
    """``print Good`` must find ``good``."""
    print_word(small_index, "GOOD")
    out = capsys.readouterr().out

    assert "http://a/" in out


def test_print_word_empty_handled(
    small_index: InvertedIndex, capsys: pytest.CaptureFixture[str]
) -> None:
    print_word(small_index, "   ")
    out = capsys.readouterr().out

    assert "Empty" in out or "empty" in out


# --------------------------------------------------------------------------- #
# find: basic matching                                                        #
# --------------------------------------------------------------------------- #


def test_find_single_word_returns_matching_urls(
    small_index: InvertedIndex,
) -> None:
    result = find(small_index, "morning")
    assert result == ["http://b/"]


def test_find_word_not_in_index_returns_empty(
    small_index: InvertedIndex,
) -> None:
    assert find(small_index, "nonexistent") == []


def test_find_empty_query_returns_empty_list(
    small_index: InvertedIndex,
) -> None:
    """An empty (or whitespace-only) query yields no results.

    This is documented behaviour — see ``find``'s docstring. The CLI
    surfaces it as a friendly "no results" message rather than an error.
    """
    assert find(small_index, "") == []
    assert find(small_index, "   ") == []
    assert find(small_index, "!!! ???") == []


# --------------------------------------------------------------------------- #
# find: AND semantics                                                         #
# --------------------------------------------------------------------------- #


def test_find_multi_word_uses_and_semantics(
    small_index: InvertedIndex,
) -> None:
    """``good night`` must match only the page that contains BOTH terms."""
    result = find(small_index, "good night")
    assert result == ["http://a/"]


def test_find_multi_word_with_no_overlap_returns_empty(
    small_index: InvertedIndex,
) -> None:
    """No document contains both ``morning`` and ``bad`` — expect ``[]``."""
    assert find(small_index, "morning bad") == []


# --------------------------------------------------------------------------- #
# find: ranking                                                               #
# --------------------------------------------------------------------------- #


def test_find_higher_frequency_ranks_higher() -> None:
    """A document with more occurrences of the query term should rank first.

    A third document that does not contain the term is included so the IDF
    factor is non-zero — under the brief's ``log(N/df)`` formula a term that
    appears in every document has IDF zero and TF can no longer differentiate.
    """
    pages = {
        "http://few/": "<p>cat dog dog dog dog</p>",
        "http://many/": "<p>cat cat cat cat cat dog</p>",
        "http://other/": "<p>fish bird</p>",
    }
    idx = Indexer().build_index(pages)
    result = find(idx, "cat")

    assert result == ["http://many/", "http://few/"]


def test_find_ranking_combines_query_terms() -> None:
    """For multi-term queries TF-IDF scores are summed across terms.

    A distractor document keeps the document frequency below the corpus size
    so the IDF stays non-zero for both query terms.
    """
    pages = {
        "http://long/": "<p>" + "filler " * 50 + "apple banana</p>",
        "http://short/": "<p>apple banana</p>",
        "http://other/": "<p>cherry date elderberry</p>",
    }
    idx = Indexer().build_index(pages)
    result = find(idx, "apple banana")

    assert result[0] == "http://short/"


def test_find_is_case_insensitive(small_index: InvertedIndex) -> None:
    """Querying ``GOOD NIGHT`` must yield the same result as ``good night``."""
    assert find(small_index, "GOOD NIGHT") == find(small_index, "good night")


def test_find_strips_query_punctuation(small_index: InvertedIndex) -> None:
    """``good, night!`` must match the page that contains both terms."""
    assert find(small_index, "good, night!") == ["http://a/"]


# --------------------------------------------------------------------------- #
# parse_query                                                                 #
# --------------------------------------------------------------------------- #


def test_parse_query_no_quotes_returns_only_singletons() -> None:
    singletons, phrases = parse_query("good morning friends")
    assert singletons == ["good", "morning", "friends"]
    assert phrases == []


def test_parse_query_extracts_quoted_phrase() -> None:
    singletons, phrases = parse_query('"good night"')
    assert singletons == []
    assert phrases == [["good", "night"]]


def test_parse_query_mixes_phrase_and_singletons() -> None:
    singletons, phrases = parse_query('cat "good night" dog')
    assert singletons == ["cat", "dog"]
    assert phrases == [["good", "night"]]


def test_has_phrase_detects_quotes() -> None:
    assert has_phrase('find "good night"')
    assert not has_phrase("find good night")


# --------------------------------------------------------------------------- #
# find: phrase queries                                                        #
# --------------------------------------------------------------------------- #


def test_find_phrase_requires_consecutive_positions() -> None:
    """Only documents where phrase tokens are *adjacent* should match."""
    pages = {
        "http://adjacent/": "<p>good night world</p>",
        "http://separated/": "<p>good morning night</p>",
    }
    idx = Indexer().build_index(pages)

    assert find(idx, '"good night"') == ["http://adjacent/"]


def test_find_phrase_respects_order() -> None:
    """``"good night"`` must NOT match a page that only has ``night good``."""
    pages = {
        "http://forward/": "<p>good night</p>",
        "http://reversed/": "<p>night good</p>",
    }
    idx = Indexer().build_index(pages)

    assert find(idx, '"good night"') == ["http://forward/"]


def test_find_single_word_phrase_works(small_index: InvertedIndex) -> None:
    """A one-token phrase reduces to a normal lookup."""
    assert find(small_index, '"morning"') == ["http://b/"]


def test_find_phrase_with_extra_singleton_intersects() -> None:
    """``"good night" friends`` keeps only docs with the phrase AND ``friends``."""
    pages = {
        "http://both/": "<p>good night with friends</p>",
        "http://no_phrase/": "<p>good morning night friends</p>",
        "http://no_friend/": "<p>good night alone</p>",
    }
    idx = Indexer().build_index(pages)

    assert find(idx, '"good night" friends') == ["http://both/"]


def test_find_deterministic_on_score_ties() -> None:
    """Equal-scoring documents must come out in a stable, alphabetical order."""
    pages = {
        "http://b/": "<p>only word</p>",
        "http://a/": "<p>only word</p>",
        "http://c/": "<p>only word</p>",
    }
    idx = Indexer().build_index(pages)
    result = find(idx, "only")

    assert result == ["http://a/", "http://b/", "http://c/"]
