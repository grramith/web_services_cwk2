"""Inverted-index construction.

The :class:`Indexer` consumes a ``{url: html}`` mapping (the output of
:class:`src.crawler.Crawler`) and produces a nested-dict inverted index of the
form::

    {
        "word": {
            "https://quotes.toscrape.com/page/1/": {
                "frequency": 3,
                "positions": [12, 47, 89],
            },
            ...
        },
        ...
    }

Frequencies and positions are both tracked because they enable two different
features at query time: frequencies feed TF-IDF ranking, and positions allow
phrase queries or proximity-aware ranking later. The position list is the
0-indexed location of each occurrence in the document's tokenised stream.

Tokenisation rules (per the brief):

* Lowercase everything.
* Strip punctuation.
* Split on whitespace.
* Stopwords are *not* removed — keeping them lets ``print the`` still work.

The :func:`extract_text` and :func:`tokenize` helpers are intentionally pure
functions so they can be unit-tested without constructing an :class:`Indexer`.
"""

from __future__ import annotations

import functools
import logging
import re
import string
from typing import Dict, List

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


#: Per-document statistics for one word.
PostingEntry = Dict[str, object]
#: ``{url: PostingEntry}`` — all documents containing one word.
Posting = Dict[str, PostingEntry]
#: ``{word: Posting}`` — the full inverted index.
InvertedIndex = Dict[str, Posting]


# Pre-compiled translation table for stripping punctuation. Built once at
# import time so :func:`tokenize` stays fast on large corpora.
_PUNCT_TABLE = str.maketrans({ch: " " for ch in string.punctuation})

# Some characters that show up on quotes.toscrape.com but are not in
# ``string.punctuation`` (smart quotes, em-dash, ellipsis, non-breaking space).
_EXTRA_PUNCT = "“”‘’–—…\xa0"
_EXTRA_TABLE = str.maketrans({ch: " " for ch in _EXTRA_PUNCT})


@functools.lru_cache(maxsize=1)
def _get_stemmer():
    """Return a singleton :class:`nltk.stem.PorterStemmer` instance.

    The stemmer is constructed lazily so importing :mod:`src.indexer`
    in a no-stem run never imports nltk. Tests that exercise the
    no-stem path therefore stay fast and never need the optional
    dependency.
    """
    from nltk.stem import PorterStemmer  # local import — see docstring
    return PorterStemmer()


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


def tokenize(text: str, *, stem: bool = False) -> List[str]:
    """Tokenise ``text`` into lowercase, punctuation-free tokens.

    Args:
        text: Arbitrary text.
        stem: When ``True``, run each token through
            :class:`nltk.stem.PorterStemmer` before returning. Defaults to
            ``False`` so existing behaviour and tests are unaffected.

    Returns:
        List of tokens in their original order. Empty fragments produced by
        adjacent punctuation are dropped.
    """
    lowered = text.lower()
    cleaned = lowered.translate(_PUNCT_TABLE).translate(_EXTRA_TABLE)
    tokens = [tok for tok in cleaned.split() if tok]
    if stem and tokens:
        stemmer = _get_stemmer()
        tokens = [stemmer.stem(tok) for tok in tokens]
    return tokens


class Indexer:
    """Builds an inverted index from a ``{url: html}`` mapping.

    Args:
        stem: When ``True``, the indexer applies :class:`nltk.stem.PorterStemmer`
            to every token at index time so that morphological variants
            (``run`` / ``running`` / ``runs``) collapse onto the same posting.
            Defaults to ``False`` to preserve the un-stemmed behaviour the
            rest of the project assumes.
    """

    def __init__(self, stem: bool = False) -> None:
        self.stem = stem

    def build_index(self, pages: Dict[str, str]) -> InvertedIndex:
        """Construct an inverted index for the supplied pages.

        Args:
            pages: Mapping from canonical URL to the HTML body of that page.

        Returns:
            Nested dictionary keyed by word, then by URL, with per-document
            ``frequency`` and ``positions`` fields.
        """
        index: InvertedIndex = {}
        for url, html in pages.items():
            text = extract_text(html)
            tokens = tokenize(text, stem=self.stem)
            self._add_document(index, url, tokens)
            logger.debug("Indexed %s (%d tokens)", url, len(tokens))
        logger.info("Index built: %d unique terms across %d pages.",
                    len(index), len(pages))
        return index

    @staticmethod
    def _add_document(
        index: InvertedIndex, url: str, tokens: List[str]
    ) -> None:
        """Merge one document's tokens into ``index`` in place."""
        for position, token in enumerate(tokens):
            posting = index.setdefault(token, {})
            entry = posting.setdefault(url, {"frequency": 0, "positions": []})
            entry["frequency"] = int(entry["frequency"]) + 1  # type: ignore[arg-type]
            positions = entry["positions"]
            assert isinstance(positions, list)
            positions.append(position)
