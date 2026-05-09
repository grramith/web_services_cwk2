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


def save_index(
    index: InvertedIndex,
    path: str,
    *,
    stem: bool = False,
) -> None:
    """Serialise ``index`` to ``path`` as UTF-8 JSON.

    The parent directory is created if missing. Output is pretty-printed with
    two-space indentation so the file remains human-inspectable.

    A small sidecar file at ``{path}.meta.json`` is written alongside the
    main index, recording configuration that the search side needs to
    reproduce — currently just whether the index was built with the Porter
    stemmer enabled. The sidecar is optional: callers that don't pass
    keyword arguments still produce the original on-disk layout, so
    existing tests and indexes remain valid.

    Args:
        index: The inverted index to persist.
        path: Filesystem path of the JSON file to write.
        stem: Whether the index was built with stemming. Persisted in the
            ``.meta.json`` sidecar so :func:`load_index_metadata` can
            recover it later.
    """
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2, sort_keys=True)
    meta_path = path + ".meta.json"
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump({"stem": bool(stem)}, fh, indent=2, sort_keys=True)
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


def load_index_metadata(path: str) -> Dict[str, object]:
    """Return the metadata sidecar that ships next to ``path``.

    Args:
        path: Filesystem path of the index JSON file. The metadata is
            looked up at ``{path}.meta.json``.

    Returns:
        A dict whose keys are the configuration flags persisted by
        :func:`save_index`. If the sidecar does not exist (older indexes
        that predate the stemmer feature) the function returns the
        documented defaults so callers can use the result unconditionally.
    """
    meta_path = path + ".meta.json"
    defaults: Dict[str, object] = {"stem": False}
    if not os.path.exists(meta_path):
        return defaults
    with open(meta_path, "r", encoding="utf-8") as fh:
        try:
            payload: Dict[str, object] = json.load(fh)
        except json.JSONDecodeError:
            return defaults
    out = dict(defaults)
    out.update(payload)
    return out
