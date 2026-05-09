"""Unit tests for :mod:`src.search`."""

from __future__ import annotations

import pytest

from src.indexer import Indexer, InvertedIndex
from src.search import (
    find,
    has_operators,
    has_phrase,
    parse_query,
    print_word,
)


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


def test_parse_query_no_quotes_returns_single_group_of_singletons() -> None:
    groups = parse_query("good morning friends")
    assert len(groups) == 1
    assert groups[0].positives == ["good", "morning", "friends"]
    assert groups[0].phrases == []
    assert groups[0].negatives == []


def test_parse_query_extracts_quoted_phrase() -> None:
    groups = parse_query('"good night"')
    assert len(groups) == 1
    assert groups[0].positives == []
    assert groups[0].phrases == [["good", "night"]]


def test_parse_query_mixes_phrase_and_singletons() -> None:
    groups = parse_query('cat "good night" dog')
    assert len(groups) == 1
    assert groups[0].positives == ["cat", "dog"]
    assert groups[0].phrases == [["good", "night"]]


def test_parse_query_uppercase_and_is_no_op() -> None:
    """``AND`` is the redundant default — must not appear as a search term."""
    groups = parse_query("love AND life")
    assert len(groups) == 1
    assert groups[0].positives == ["love", "life"]


def test_parse_query_uppercase_or_splits_into_groups() -> None:
    groups = parse_query("love OR hate")
    assert len(groups) == 2
    assert groups[0].positives == ["love"]
    assert groups[1].positives == ["hate"]


def test_parse_query_uppercase_not_marks_negation() -> None:
    groups = parse_query("love NOT hate")
    assert len(groups) == 1
    assert groups[0].positives == ["love"]
    assert groups[0].negatives == ["hate"]


def test_parse_query_lowercase_words_are_not_operators() -> None:
    """Prose like ``cats and dogs`` must search for the literal words."""
    groups = parse_query("cats and dogs")
    assert len(groups) == 1
    assert groups[0].positives == ["cats", "and", "dogs"]
    assert groups[0].negatives == []


def test_parse_query_or_with_phrases_and_negation() -> None:
    """Combined query: ``love NOT hate OR "good friends"``."""
    groups = parse_query('love NOT hate OR "good friends"')
    assert len(groups) == 2
    assert groups[0].positives == ["love"]
    assert groups[0].negatives == ["hate"]
    assert groups[1].phrases == [["good", "friends"]]


def test_has_phrase_detects_quotes() -> None:
    assert has_phrase('find "good night"')
    assert not has_phrase("find good night")


def test_has_operators_detects_uppercase_only() -> None:
    assert has_operators("love AND life")
    assert has_operators("love OR life")
    assert has_operators("love NOT hate")
    assert not has_operators("love and life")
    assert not has_operators("love")


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


# --------------------------------------------------------------------------- #
# find: boolean operators                                                     #
# --------------------------------------------------------------------------- #


def test_find_uppercase_and_matches_simple_and(
    small_index: InvertedIndex,
) -> None:
    """``love AND life`` must behave identically to ``love life``."""
    pages = {
        "http://both/": "<p>love life</p>",
        "http://only_love/": "<p>love alone</p>",
    }
    idx = Indexer().build_index(pages)
    assert find(idx, "love AND life") == find(idx, "love life")
    assert find(idx, "love AND life") == ["http://both/"]


def test_find_uppercase_or_unions_results() -> None:
    """``love OR life`` must return the union of matches."""
    pages = {
        "http://has_love/": "<p>only love here</p>",
        "http://has_life/": "<p>only life here</p>",
        "http://has_neither/": "<p>fish chips</p>",
    }
    idx = Indexer().build_index(pages)
    result = find(idx, "love OR life")
    assert set(result) == {"http://has_love/", "http://has_life/"}


def test_find_uppercase_not_excludes_pages(
    small_index: InvertedIndex,
) -> None:
    """``good NOT night`` keeps pages with ``good`` but drops those with ``night``."""
    # http://a/ has good+night → excluded.
    # http://b/ has good (no night) → kept.
    assert find(small_index, "good NOT night") == ["http://b/"]


def test_find_only_not_returns_empty(small_index: InvertedIndex) -> None:
    """A pure-NOT query has no positive anchor — must return empty."""
    assert find(small_index, "NOT night") == []


def test_find_lowercase_and_or_not_are_words(small_index: InvertedIndex) -> None:
    """Lowercase ``and``/``or``/``not`` are ordinary search terms."""
    # ``find good and night`` should AND-search for good+and+night;
    # the small_index doesn't have the word "and", so result is empty.
    assert find(small_index, "good and night") == []


def test_find_or_with_not_in_one_arm() -> None:
    """``love NOT hate OR fish`` = ``(love NOT hate) ∪ fish``."""
    pages = {
        "http://love_only/": "<p>only love here</p>",
        "http://love_hate/": "<p>love and hate together</p>",
        "http://fish/": "<p>just fish</p>",
        "http://nothing/": "<p>banana</p>",
    }
    idx = Indexer().build_index(pages)
    result = set(find(idx, "love NOT hate OR fish"))
    assert result == {"http://love_only/", "http://fish/"}


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
