"""Query helpers for the inverted index.

This module currently exposes :func:`print_word`, which pretty-prints the
posting for a single term. Ranked retrieval is added in a follow-up commit.
"""

from __future__ import annotations

import logging

from src.indexer import InvertedIndex

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
