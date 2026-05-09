"""Reproducible micro-benchmarks for the quotes search engine.

Four numbers are reported for the README's ``## Benchmarks`` section:

1. **Build time** — wall-clock seconds to convert a synthetic
   ``{url: html}`` fixture into an inverted index. The fixture is
   generated deterministically from a fixed seed, so the time is
   reproducible across machines (modulo CPU speed).
2. **Load time** — wall-clock seconds for :func:`src.storage.load_index`
   to deserialise the committed ``data/index.json``.
3. **Mean query time** — average wall-clock seconds for one
   :func:`src.search.find` call, over fifty single-term queries sampled
   (with a fixed seed) from the corpus vocabulary. The first call is
   discarded as a warm-up so JIT-y caches and import-time work do not
   skew the average.
4. **Index size** — bytes occupied by ``data/index.json`` on disk.

The harness must be runnable offline. No live HTTP is performed; every
HTML fixture is synthesised in-memory.

Run from the repository root::

    python -m benchmarks.run_benchmarks
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import string
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.indexer import Indexer  # noqa: E402
from src.search import find  # noqa: E402
from src.storage import load_index  # noqa: E402


DEFAULT_QUERIES = 50
DEFAULT_FIXTURE_PAGES = 50
DEFAULT_WORDS_PER_PAGE = 250
SEED = 0xC0FFEE


@dataclass(frozen=True)
class BenchmarkReport:
    """Aggregated numbers consumed by the README and the regression test."""

    build_seconds: float
    build_pages: int
    build_tokens_total: int
    load_seconds: float
    load_terms: int
    query_seconds_mean: float
    query_seconds_median: float
    query_seconds_max: float
    query_count: int
    index_bytes: int


# --------------------------------------------------------------------------- #
# Fixture synthesis                                                           #
# --------------------------------------------------------------------------- #


_VOCAB = (
    "love life truth wisdom imagination friendship sister courage "
    "happiness journey adventure music story book quote light "
    "darkness silence laughter dream hope freedom courage memory "
    "winter summer autumn spring water fire earth wind"
).split()


def _make_pages(
    n_pages: int = DEFAULT_FIXTURE_PAGES,
    words_per_page: int = DEFAULT_WORDS_PER_PAGE,
    seed: int = SEED,
) -> Dict[str, str]:
    """Synthesise a deterministic ``{url: html}`` fixture.

    Each page is a paragraph of words drawn from a small fixed vocabulary,
    wrapped in valid HTML. Using a fixed RNG seed makes the resulting
    fixture (and therefore the build-time measurement) reproducible.

    Args:
        n_pages: Number of fixture pages to generate.
        words_per_page: Approximate token count per page.
        seed: Seed for :class:`random.Random`. Defaults to ``SEED``.

    Returns:
        ``{url: html}`` mapping suitable for
        :meth:`src.indexer.Indexer.build_index`.
    """
    rng = random.Random(seed)
    pages: Dict[str, str] = {}
    for i in range(n_pages):
        words = rng.choices(_VOCAB, k=words_per_page)
        body = " ".join(words)
        url = f"https://example.invalid/bench/{i:03d}/"
        pages[url] = (
            "<html><head><title>Bench page</title></head>"
            f"<body><p>{body}</p></body></html>"
        )
    return pages


# --------------------------------------------------------------------------- #
# Measurements                                                                #
# --------------------------------------------------------------------------- #


def _measure_build(pages: Dict[str, str]) -> tuple[float, int]:
    """Return ``(seconds, total_tokens_indexed)`` for one build pass."""
    indexer = Indexer()
    start = time.perf_counter()
    index = indexer.build_index(pages)
    elapsed = time.perf_counter() - start
    total_tokens = sum(
        sum(int(entry.get("frequency", 0)) for entry in posting.values())
        for posting in index.values()
    )
    return elapsed, total_tokens


def _measure_load(index_path: Path) -> tuple[float, int]:
    """Return ``(seconds, term_count)`` for one ``load_index`` pass."""
    start = time.perf_counter()
    index = load_index(str(index_path))
    elapsed = time.perf_counter() - start
    return elapsed, len(index)


def _sample_query_terms(
    index: dict, n_queries: int, seed: int = SEED
) -> List[str]:
    """Return ``n_queries`` distinct terms from the index vocabulary.

    Sampling without replacement makes the benchmark deterministic and
    avoids scoring the same posting list fifty times in a row, which
    would let CPU caches give a misleadingly fast number.
    """
    rng = random.Random(seed)
    terms = list(index.keys())
    rng.shuffle(terms)
    return terms[:n_queries]


def _measure_queries(
    index: dict, n_queries: int = DEFAULT_QUERIES
) -> tuple[float, float, float]:
    """Return ``(mean, median, max)`` seconds across ``n_queries`` queries.

    A single warm-up call is discarded so that lazy module init and the
    first JIT-y dictionary lookup don't skew the mean.
    """
    terms = _sample_query_terms(index, n_queries)
    if not terms:
        return 0.0, 0.0, 0.0

    # Warm-up — result discarded.
    find(index, terms[0])

    timings: List[float] = []
    for term in terms:
        start = time.perf_counter()
        find(index, term)
        timings.append(time.perf_counter() - start)

    return (
        statistics.fmean(timings),
        statistics.median(timings),
        max(timings),
    )


def _measure_size(index_path: Path) -> int:
    """Return the on-disk size of ``index_path`` in bytes."""
    return index_path.stat().st_size


# --------------------------------------------------------------------------- #
# Top-level driver                                                            #
# --------------------------------------------------------------------------- #


def run(
    *,
    index_path: Path,
    results_path: Path,
    n_queries: int = DEFAULT_QUERIES,
    n_pages: int = DEFAULT_FIXTURE_PAGES,
    words_per_page: int = DEFAULT_WORDS_PER_PAGE,
) -> BenchmarkReport:
    """Run every measurement and persist the report.

    Args:
        index_path: Path to the production index used for load / query
            timings. Defaults to ``data/index.json`` via the CLI.
        results_path: Where to write the JSON report.
        n_queries: Number of random vocabulary terms to query.
        n_pages: Fixture page count for the build measurement.
        words_per_page: Approximate per-page token count.

    Returns:
        :class:`BenchmarkReport` with all measurements.
    """
    pages = _make_pages(n_pages=n_pages, words_per_page=words_per_page)
    build_seconds, total_tokens = _measure_build(pages)

    load_seconds, term_count = _measure_load(index_path)
    index = load_index(str(index_path))
    mean_q, median_q, max_q = _measure_queries(index, n_queries=n_queries)

    report = BenchmarkReport(
        build_seconds=build_seconds,
        build_pages=n_pages,
        build_tokens_total=total_tokens,
        load_seconds=load_seconds,
        load_terms=term_count,
        query_seconds_mean=mean_q,
        query_seconds_median=median_q,
        query_seconds_max=max_q,
        query_count=n_queries,
        index_bytes=_measure_size(index_path),
    )

    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(asdict(report), indent=2) + "\n")

    print(format_markdown(report))
    return report


def format_markdown(report: BenchmarkReport) -> str:
    """Render ``report`` as the markdown block the README embeds."""
    rows = [
        ("Build (synthetic fixture)",
         f"{report.build_seconds * 1000:.2f} ms",
         f"{report.build_pages} pages, {report.build_tokens_total} tokens"),
        ("Load `data/index.json`",
         f"{report.load_seconds * 1000:.2f} ms",
         f"{report.load_terms} terms"),
        ("Mean query (warm)",
         f"{report.query_seconds_mean * 1000:.3f} ms",
         f"median {report.query_seconds_median * 1000:.3f} ms / "
         f"max {report.query_seconds_max * 1000:.3f} ms over "
         f"{report.query_count} terms"),
        ("Index size on disk",
         f"{report.index_bytes / 1024:.1f} KiB",
         f"{report.index_bytes} bytes"),
    ]
    header = "| Measurement | Value | Notes |\n| --- | --- | --- |"
    body = "\n".join(f"| {a} | {b} | {c} |" for a, b, c in rows)
    return f"{header}\n{body}"


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index", default=str(ROOT / "data" / "index.json"), type=Path
    )
    parser.add_argument(
        "--results",
        default=str(ROOT / "benchmarks" / "results.json"),
        type=Path,
    )
    parser.add_argument("--queries", type=int, default=DEFAULT_QUERIES)
    parser.add_argument("--pages", type=int, default=DEFAULT_FIXTURE_PAGES)
    parser.add_argument("--words", type=int, default=DEFAULT_WORDS_PER_PAGE)
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    run(
        index_path=Path(args.index),
        results_path=Path(args.results),
        n_queries=args.queries,
        n_pages=args.pages,
        words_per_page=args.words,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
