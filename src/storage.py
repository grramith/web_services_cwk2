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
from typing import Dict

from src.indexer import InvertedIndex

logger = logging.getLogger(__name__)


class IndexNotFoundError(FileNotFoundError):
    """Raised by :func:`load_index` when the requested file does not exist.

    Inherits from :class:`FileNotFoundError` so callers that catch the
    standard exception still work, while callers that want a more specific
    error get one.
    """


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


def load_index(path: str) -> InvertedIndex:
    """Load a JSON-serialised inverted index from disk.

    Args:
        path: Filesystem path of the JSON file to read.

    Returns:
        The deserialised inverted index.

    Raises:
        IndexNotFoundError: If ``path`` does not exist.
        ValueError: If the file exists but is not valid JSON.
    """
    if not os.path.exists(path):
        raise IndexNotFoundError(
            f"No index file at {path!r}. Run 'build' first or check the path."
        )
    with open(path, "r", encoding="utf-8") as fh:
        try:
            data: Dict = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Index file at {path!r} is not valid JSON: {exc}"
            ) from exc
    logger.info("Loaded index with %d terms from %s", len(data), path)
    return data  # type: ignore[return-value]
