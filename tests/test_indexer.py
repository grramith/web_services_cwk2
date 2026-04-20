"""Unit tests for :mod:`src.indexer`."""

from __future__ import annotations

from src.indexer import Indexer, extract_text, tokenize


# --------------------------------------------------------------------------- #
# tokenize                                                                    #
# --------------------------------------------------------------------------- #


def test_tokenize_lowercases() -> None:
    assert tokenize("Hello WORLD") == ["hello", "world"]


def test_tokenize_strips_punctuation() -> None:
    assert tokenize("Good, day! Don't stop.") == ["good", "day", "don", "t", "stop"]


def test_tokenize_handles_smart_quotes_and_dashes() -> None:
    """Smart quotes and em-dashes occur on the live site; they must be stripped."""
    assert tokenize("“Hello” — world…") == ["hello", "world"]


def test_tokenize_collapses_whitespace() -> None:
    assert tokenize("   foo\t\nbar   baz ") == ["foo", "bar", "baz"]


def test_tokenize_empty_string_returns_empty_list() -> None:
    assert tokenize("") == []


def test_tokenize_pure_punctuation_returns_empty_list() -> None:
    assert tokenize("!!! ??? ...") == []


# --------------------------------------------------------------------------- #
# extract_text                                                                #
# --------------------------------------------------------------------------- #


def test_extract_text_drops_script_and_style() -> None:
    html = (
        "<html><head><style>p{color:red}</style></head>"
        "<body><script>alert(1)</script>"
        "<p>Visible text</p></body></html>"
    )
    text = extract_text(html)
    assert "Visible text" in text
    assert "alert" not in text
    assert "color" not in text


def test_extract_text_separates_block_elements() -> None:
    """``<p>foo</p><p>bar</p>`` must yield ``foo bar``, not ``foobar``."""
    html = "<html><body><p>foo</p><p>bar</p></body></html>"
    assert extract_text(html) == "foo bar"


def test_extract_text_normalises_whitespace() -> None:
    html = "<html><body>   hello   \n\n   world   </body></html>"
    assert extract_text(html) == "hello world"


# --------------------------------------------------------------------------- #
# build_index                                                                 #
# --------------------------------------------------------------------------- #


def test_build_index_simple_single_page() -> None:
    """A known input document must yield the expected nested structure."""
    pages = {"http://example.com/": "<p>good day good night</p>"}
    idx = Indexer().build_index(pages)

    assert set(idx.keys()) == {"good", "day", "night"}
    assert idx["good"]["http://example.com/"]["frequency"] == 2
    assert idx["good"]["http://example.com/"]["positions"] == [0, 2]
    assert idx["day"]["http://example.com/"]["positions"] == [1]
    assert idx["night"]["http://example.com/"]["positions"] == [3]


def test_build_index_position_tracking() -> None:
    """The 0-indexed positions must match the order of tokens in the document."""
    pages = {"u": "<p>alpha beta gamma alpha gamma</p>"}
    idx = Indexer().build_index(pages)

    assert idx["alpha"]["u"]["positions"] == [0, 3]
    assert idx["beta"]["u"]["positions"] == [1]
    assert idx["gamma"]["u"]["positions"] == [2, 4]


def test_build_index_multiple_pages_aggregate_under_same_word() -> None:
    """When two pages contain the same word, both URLs must appear in its posting."""
    pages = {
        "http://a/": "<p>shared apple</p>",
        "http://b/": "<p>shared pear shared</p>",
    }
    idx = Indexer().build_index(pages)

    shared = idx["shared"]
    assert set(shared.keys()) == {"http://a/", "http://b/"}
    assert shared["http://a/"]["frequency"] == 1
    assert shared["http://b/"]["frequency"] == 2
    assert shared["http://b/"]["positions"] == [0, 2]

    # Unique terms must only appear under their respective documents.
    assert list(idx["apple"].keys()) == ["http://a/"]
    assert list(idx["pear"].keys()) == ["http://b/"]


def test_build_index_is_case_insensitive() -> None:
    """Different cases of the same word must collapse into one posting."""
    pages = {"u": "<p>Good GOOD good</p>"}
    idx = Indexer().build_index(pages)

    assert list(idx.keys()) == ["good"]
    assert idx["good"]["u"]["frequency"] == 3


def test_build_index_empty_pages_returns_empty_index() -> None:
    assert Indexer().build_index({}) == {}


def test_build_index_strips_html_tags_from_index_terms() -> None:
    """Tag names like ``html`` or ``body`` must not leak into the index."""
    pages = {"u": "<html><body><p>only word</p></body></html>"}
    idx = Indexer().build_index(pages)

    assert set(idx.keys()) == {"only", "word"}
