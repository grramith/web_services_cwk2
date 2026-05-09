"""Performance regression tests for :func:`src.search.find`.

The target is a soft 50 ms upper bound on a single ``find`` call against a
small in-memory index. The threshold sits well above the warm wall-clock
time observed locally (median ~1 ms, max ~8 ms in
``benchmarks/results.json``), so it should only trip if a future change
introduces an algorithmic regression rather than tripping on CI noise.

A single warm-up call is performed before timing so import-time work and
cold dictionary look-ups don't pollute the measurement.
"""

from __future__ import annotations

import random
import time

import pytest

from src.indexer import Indexer
from src.search import find


# 50 ms ceiling per the project specification. CI runners are typically
# slower than developer laptops, but the gap to our observed times is
# wide enough that this is still a meaningful regression test.
FIND_BUDGET_SECONDS = 0.050


def _build_synthetic_index(n_pages: int = 20, words_per_page: int = 200):
    """Return an Indexer-built index over a deterministic synthetic corpus."""
    rng = random.Random(0xBADCAFE)
    vocabulary = (
        "love life truth wisdom imagination friendship sister courage "
        "happiness journey adventure music story book quote"
    ).split()
    pages = {
        f"http://test/{i:03d}/": (
            "<p>" + " ".join(rng.choices(vocabulary, k=words_per_page)) + "</p>"
        )
        for i in range(n_pages)
    }
    return Indexer().build_index(pages)


@pytest.fixture(scope="module")
def synthetic_index():
    """A 20-page synthetic index built once per module."""
    return _build_synthetic_index()


def test_find_single_term_under_budget(synthetic_index):
    """Single-term ``find`` must complete in under :data:`FIND_BUDGET_SECONDS`."""
    # Warm-up — discarded.
    find(synthetic_index, "love")

    start = time.perf_counter()
    find(synthetic_index, "love")
    elapsed = time.perf_counter() - start

    assert elapsed < FIND_BUDGET_SECONDS, (
        f"find('love') took {elapsed * 1000:.2f} ms, "
        f"exceeding the {FIND_BUDGET_SECONDS * 1000:.0f} ms budget"
    )


def test_find_multi_term_under_budget(synthetic_index):
    """AND-style multi-term queries should also stay under budget."""
    find(synthetic_index, "love truth")  # warm-up

    start = time.perf_counter()
    find(synthetic_index, "love truth")
    elapsed = time.perf_counter() - start

    assert elapsed < FIND_BUDGET_SECONDS, (
        f"find('love truth') took {elapsed * 1000:.2f} ms, "
        f"exceeding the {FIND_BUDGET_SECONDS * 1000:.0f} ms budget"
    )


def test_find_phrase_under_budget(synthetic_index):
    """Phrase queries do extra position-list work but still fit the budget."""
    find(synthetic_index, '"love truth"')  # warm-up

    start = time.perf_counter()
    find(synthetic_index, '"love truth"')
    elapsed = time.perf_counter() - start

    assert elapsed < FIND_BUDGET_SECONDS, (
        f"phrase find took {elapsed * 1000:.2f} ms, "
        f"exceeding the {FIND_BUDGET_SECONDS * 1000:.0f} ms budget"
    )
