"""Query processing against the inverted index.

Two public entry points:

* :func:`print_word` — pretty-prints the posting for a single term, used by
  the CLI's ``print`` command.
* :func:`find` — answers an AND-query and returns the matching URLs ranked
  by **TF-IDF**.

TF-IDF formula
--------------

For document ``d`` and query term ``t``:

* ``tf(t, d) = freq(t, d) / total_tokens(d)`` — relative frequency. The
  document's total token count is approximated as the sum of all term
  frequencies in that document, which is exact for a single-document
  vocabulary and a tight upper bound otherwise.
* ``idf(t)   = log(N / df(t))`` — natural log, with ``N`` = number of
  documents in the corpus and ``df(t)`` = number of documents containing
  ``t``. We use the un-smoothed form because every query term is, by
  construction, present in at least one document (otherwise the AND-set is
  empty and we never reach the ranking step).
* For multi-term queries the per-term TF-IDF scores are summed.

Ties (same score) are broken by URL alphabetical order so results are
deterministic — important for testability.
"""

from __future__ import annotations

import logging
import math
from typing import Dict, List, Set

from src.indexer import InvertedIndex, tokenize

logger = logging.getLogger(__name__)


def print_word(index: InvertedIndex, word: str) -> None:
    """Print the inverted-index entry for ``word`` to stdout.

    The output lists each URL containing the word, its frequency on that
    page, and the positions where it occurs. If the word does not appear in
    the index a friendly message is printed instead.

    Args:
        index: The inverted index to query.
        word: Term to print. Case is normalised before lookup.
    """
    key = word.strip().lower()
    if not key:
        print("Empty word.")
        return

    posting = index.get(key)
    if not posting:
        print(f"'{key}' is not in the index.")
        return

    print(f"'{key}' appears in {len(posting)} document(s):")
    for url in sorted(posting.keys()):
        entry = posting[url]
        freq = entry.get("frequency", 0)
        positions = entry.get("positions", [])
        print(f"  {url}")
        print(f"    frequency: {freq}")
        print(f"    positions: {positions}")


def find(index: InvertedIndex, query: str) -> List[str]:
    """Return URLs matching ``query``, ranked by descending TF-IDF.

    Multi-word queries use AND semantics — only documents containing
    *every* query term survive the intersection. The surviving documents
    are then ranked by the sum of TF-IDF scores across the query terms,
    with ties broken alphabetically by URL.

    Args:
        index: The inverted index to query.
        query: Free-text query string. Tokenised with the same rules as the
            index, so case and punctuation don't matter.

    Returns:
        Ordered list of URLs (most relevant first). Empty list if the query
        is empty or no document contains all terms.
    """
    terms = tokenize(query)
    if not terms:
        return []

    matching_urls = _intersect_postings(index, terms)
    if not matching_urls:
        return []

    total_docs = _count_total_documents(index)
    scored = [
        (url, _score(index, terms, url, total_docs)) for url in matching_urls
    ]
    # Sort by score desc, then URL asc, for deterministic ordering.
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return [url for url, _ in scored]


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _intersect_postings(
    index: InvertedIndex, terms: List[str]
) -> Set[str]:
    """Return the set of URLs that contain every term in ``terms``."""
    url_sets = []
    for term in terms:
        posting = index.get(term)
        if not posting:
            return set()
        url_sets.append(set(posting.keys()))
    # Intersect smallest-first for a tiny perf win on skewed indexes.
    url_sets.sort(key=len)
    result = url_sets[0]
    for other in url_sets[1:]:
        result &= other
        if not result:
            break
    return result


def _count_total_documents(index: InvertedIndex) -> int:
    """Return the number of distinct documents represented in ``index``."""
    seen: Set[str] = set()
    for posting in index.values():
        seen.update(posting.keys())
    return len(seen)


def _document_length(index: InvertedIndex, url: str) -> int:
    """Approximate ``url``'s token count by summing all term frequencies.

    This is exact: every token in the document was added to exactly one
    posting list, contributing 1 to that posting's ``frequency`` for ``url``.
    """
    total = 0
    for posting in index.values():
        entry = posting.get(url)
        if entry is not None:
            total += int(entry.get("frequency", 0))
    return total


def _score(
    index: InvertedIndex, terms: List[str], url: str, total_docs: int
) -> float:
    """Compute the summed TF-IDF score for ``url`` against ``terms``."""
    doc_len = _document_length(index, url)
    if doc_len == 0:
        return 0.0

    score = 0.0
    for term in terms:
        posting = index.get(term, {})
        entry = posting.get(url)
        if entry is None:
            continue
        freq = int(entry.get("frequency", 0))
        df = len(posting)
        if df == 0:
            continue
        tf = freq / doc_len
        idf = math.log(total_docs / df) if total_docs > 0 else 0.0
        score += tf * idf
    return score
