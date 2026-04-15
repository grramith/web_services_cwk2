"""Tokenisation primitives for the inverted-index pipeline.

The :func:`extract_text` and :func:`tokenize` helpers are intentionally pure
functions so they can be unit-tested without constructing an indexer.

Tokenisation rules (per the brief):

* Lowercase everything.
* Strip punctuation.
* Split on whitespace.
* Stopwords are *not* removed — keeping them lets ``print the`` still work.
"""

from __future__ import annotations

import re
import string
from typing import List

from bs4 import BeautifulSoup


# Pre-compiled translation table for stripping punctuation. Built once at
# import time so :func:`tokenize` stays fast on large corpora.
_PUNCT_TABLE = str.maketrans({ch: " " for ch in string.punctuation})

# Some characters that show up on quotes.toscrape.com but are not in
# ``string.punctuation`` (smart quotes, em-dash, ellipsis, non-breaking space).
_EXTRA_PUNCT = "“”‘’–—…\xa0"
_EXTRA_TABLE = str.maketrans({ch: " " for ch in _EXTRA_PUNCT})


def extract_text(html: str) -> str:
    """Return the visible text content of an HTML document.

    Script and style blocks are dropped before extraction so their contents do
    not pollute the index. Whitespace is normalised so adjacent block-level
    elements don't run their text together.

    Args:
        html: Raw HTML markup.

    Returns:
        The visible text, with words separated by single spaces.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    # ``separator=" "`` ensures ``<p>foo</p><p>bar</p>`` becomes ``foo bar``,
    # not ``foobar``.
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> List[str]:
    """Tokenise ``text`` into lowercase, punctuation-free tokens.

    Args:
        text: Arbitrary text.

    Returns:
        List of tokens in their original order. Empty fragments produced by
        adjacent punctuation are dropped.
    """
    lowered = text.lower()
    cleaned = lowered.translate(_PUNCT_TABLE).translate(_EXTRA_TABLE)
    return [tok for tok in cleaned.split() if tok]
