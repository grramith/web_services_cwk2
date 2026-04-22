"""On-disk persistence for the inverted index.

JSON was chosen over :mod:`pickle` for three reasons:

1. **Portability.** A JSON file can be opened and inspected by any tool on
   any platform. Pickle is Python-specific and version-fragile.
2. **Safety.** Loading a pickle file from an untrusted source executes
   arbitrary code. Loading JSON does not.
3. **Markability.** During development and marking it is genuinely useful to
   open ``data/index.json`` in a text editor and eyeball the structure.

The trade-off is size — JSON is bulkier than a binary pickle — but for the
scale of ``quotes.toscrape.com`` this is negligible.

This module is intentionally separate from :mod:`src.indexer` so that the
indexing algorithm has no opinion about where its output ends up. That makes
it easy to swap in a different storage backend (SQLite, Redis, etc.) later
without touching the indexer.
"""

from __future__ import annotations

import json
import logging
import os

from src.indexer import InvertedIndex

logger = logging.getLogger(__name__)


def save_index(index: InvertedIndex, path: str) -> None:
    """Serialise ``index`` to ``path`` as UTF-8 JSON.

    The parent directory is created if missing. Output is pretty-printed with
    two-space indentation so the file remains human-inspectable.

    Args:
        index: The inverted index to persist.
        path: Filesystem path of the JSON file to write.
    """
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2, sort_keys=True)
    logger.info("Saved index with %d terms to %s", len(index), path)
