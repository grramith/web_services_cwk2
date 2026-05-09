"""Pluggable ranking functions for the inverted index.

Two scoring functions are exposed at module level so the evaluation harness
(`evaluation/evaluate.py`) can A/B them against the same candidate set:

* :func:`tfidf_score` — the classical normalised-frequency TF-IDF score
  documented in Salton & Buckley (1988) and chapter 6 of Manning, Raghavan &
  Schütze (2008).
* :func:`bm25_score` — Okapi BM25 with the ``k1`` / ``b`` parameters from
  Robertson & Zaragoza (2009), defaulting to the values most commonly cited
  for medium-length English text (``k1 = 1.5``, ``b = 0.75``).

Both functions are pure: they take an :class:`~src.indexer.InvertedIndex`,
a list of query terms, a target URL and a few corpus-level statistics, and
return a non-negative float. They never mutate the index, never read disk
and never make a network call, so they are trivially testable.

References:
    Salton, G., & Buckley, C. (1988). Term-weighting approaches in
    automatic text retrieval. Information Processing & Management,
    24(5), 513-523.

    Robertson, S., & Zaragoza, H. (2009). The Probabilistic Relevance
    Framework: BM25 and Beyond. Foundations and Trends in Information
    Retrieval, 3(4), 333-389.

    Manning, C. D., Raghavan, P., & Schütze, H. (2008). Introduction
    to Information Retrieval. Cambridge University Press.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Set

from src.indexer import InvertedIndex


__all__ = [
    "tfidf_score",
    "bm25_score",
    "document_lengths",
    "average_document_length",
    "total_documents",
]


# --------------------------------------------------------------------------- #
# Corpus-level helpers                                                        #
# --------------------------------------------------------------------------- #


def total_documents(index: InvertedIndex) -> int:
    """Return the number of distinct documents represented in ``index``.

    Args:
        index: Inverted index produced by :class:`src.indexer.Indexer`.

    Returns:
        Count of unique URLs across every posting list. Returns ``0`` for
        an empty index.
    """
    seen: Set[str] = set()
    for posting in index.values():
        seen.update(posting.keys())
    return len(seen)


def document_lengths(index: InvertedIndex) -> Dict[str, int]:
    """Compute the token length of every document in ``index``.

    Each token in the original document contributed exactly ``+1`` to the
    ``frequency`` field of one posting entry, so summing those frequencies
    per URL recovers the original document length exactly (no
    approximation is involved).

    Args:
        index: Inverted index produced by :class:`src.indexer.Indexer`.

    Returns:
        Mapping ``{url: token_count}``. Documents that do not appear in
        any posting are absent from the result.
    """
    lengths: Dict[str, int] = {}
    for posting in index.values():
        for url, entry in posting.items():
            lengths[url] = lengths.get(url, 0) + int(entry.get("frequency", 0))
    return lengths


def average_document_length(index: InvertedIndex) -> float:
    """Return the mean document length over the corpus.

    Args:
        index: Inverted index produced by :class:`src.indexer.Indexer`.

    Returns:
        Mean of :func:`document_lengths` values. Returns ``0.0`` for an
        empty index — callers must therefore guard against zero before
        passing the result to BM25's denominator.
    """
    lengths = document_lengths(index)
    if not lengths:
        return 0.0
    return sum(lengths.values()) / len(lengths)


# --------------------------------------------------------------------------- #
# Scoring functions                                                           #
# --------------------------------------------------------------------------- #


def tfidf_score(
    index: InvertedIndex,
    query_terms: Iterable[str],
    url: str,
    total_docs: int,
    doc_length: int,
) -> float:
    """Score ``url`` against ``query_terms`` using normalised TF-IDF.

    The per-term contribution is ``tf * idf`` where:

    * ``tf  = freq(term, url) / doc_length`` — the document's relative
      frequency for that term.
    * ``idf = ln(total_docs / df(term))`` — the natural-log inverse
      document frequency, un-smoothed; this matches the formulation used
      throughout chapter 6 of Manning et al. (2008).

    Per-term scores are summed across the query.

    Args:
        index: Inverted index produced by :class:`src.indexer.Indexer`.
        query_terms: Already-tokenised query terms (lowercased,
            punctuation-stripped). Repeated terms count multiple times,
            matching the bag-of-words assumption.
        url: The URL whose score is being computed. Must appear in the
            index for at least one query term, otherwise the score is 0.
        total_docs: Total number of documents in the corpus
            (`N` in the formula).
        doc_length: Total token count of ``url`` (`|D|`). When 0 the
            function returns 0.0 to avoid a divide-by-zero.

    Returns:
        Non-negative TF-IDF score. ``0.0`` for documents that contain
        none of the query terms.
    """
    if doc_length <= 0 or total_docs <= 0:
        return 0.0

    score = 0.0
    for term in query_terms:
        posting = index.get(term)
        if not posting:
            continue
        entry = posting.get(url)
        if entry is None:
            continue
        freq = int(entry.get("frequency", 0))
        df = len(posting)
        if df == 0:
            continue
        tf = freq / doc_length
        idf = math.log(total_docs / df)
        score += tf * idf
    return score


def bm25_score(
    index: InvertedIndex,
    query_terms: Iterable[str],
    url: str,
    total_docs: int,
    doc_length: int,
    avg_doc_length: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """Score ``url`` against ``query_terms`` using Okapi BM25.

    Implements the canonical BM25 formulation given in equation 7 of
    Robertson & Zaragoza (2009). The IDF component uses the additive
    ``+ 1`` form (``ln(((N - df + 0.5) / (df + 0.5)) + 1)``) so the
    score never goes negative even for terms that occur in more than
    half of the corpus, which is a real concern on a 200-page site
    where boilerplate terms like "the" or "tags" appear everywhere.

    The default parameters follow the values most commonly reported as
    robust over English document collections:

    * ``k1 = 1.5`` controls how quickly term saturation kicks in.
    * ``b  = 0.75`` controls how strongly long documents are penalised
      relative to ``avg_doc_length``.

    Args:
        index: Inverted index produced by :class:`src.indexer.Indexer`.
        query_terms: Already-tokenised query terms (bag-of-words).
        url: The document being scored.
        total_docs: Total number of documents in the corpus (``N``).
        doc_length: Token count of ``url`` (``|D|``). When 0, the
            function returns 0.0.
        avg_doc_length: Mean document length across the corpus
            (``avgdl``). Must be > 0; pass the value returned by
            :func:`average_document_length`.
        k1: BM25 ``k1`` parameter — default 1.5.
        b: BM25 ``b`` parameter — default 0.75.

    Returns:
        Non-negative BM25 score. ``0.0`` for documents that contain
        none of the query terms.
    """
    if doc_length <= 0 or total_docs <= 0 or avg_doc_length <= 0:
        return 0.0

    score = 0.0
    length_norm = 1.0 - b + b * (doc_length / avg_doc_length)

    for term in query_terms:
        posting = index.get(term)
        if not posting:
            continue
        entry = posting.get(url)
        if entry is None:
            continue
        freq = int(entry.get("frequency", 0))
        df = len(posting)
        if df == 0 or freq == 0:
            continue
        idf = math.log(((total_docs - df + 0.5) / (df + 0.5)) + 1.0)
        numerator = freq * (k1 + 1.0)
        denominator = freq + k1 * length_norm
        score += idf * (numerator / denominator)
    return score
