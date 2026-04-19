"""Unit tests for :mod:`src.indexer`."""

from __future__ import annotations

from src.indexer import extract_text, tokenize


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
