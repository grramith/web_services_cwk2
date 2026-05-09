"""Run TF-IDF and BM25 against the same candidate set and report P@k / MRR.

The harness is fully reproducible: it reads the committed queries
(``evaluation/queries.json``) and index (``data/index.json``), routes every
query through the project's existing :func:`src.search.parse_query` plus
:func:`src.search._resolve_group` to obtain candidate URLs, then scores each
candidate using both :func:`src.ranking.tfidf_score` and
:func:`src.ranking.bm25_score`. The results are printed as a markdown table
and persisted to ``evaluation/results.json``.

The design isolates *retrieval* (which candidates make the shortlist) from
*ranking* (in what order). Both rankers receive the same shortlist, so any
P@k / MRR difference is purely a property of the scoring function — not a
side-effect of one ranker pulling in extra documents.

Run with::

    python -m evaluation.evaluate

or, equivalently::

    python evaluation/evaluate.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

# Allow ``python evaluation/evaluate.py`` from a fresh shell — sys.path keeps
# ``src`` importable without a wrapper.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.indexer import InvertedIndex  # noqa: E402  (sys.path mutation)
from src.ranking import (  # noqa: E402
    average_document_length,
    bm25_score,
    document_lengths,
    tfidf_score,
    total_documents,
)
from src.search import _resolve_group, parse_query  # noqa: E402
from src.storage import load_index  # noqa: E402


DEFAULT_K = 5


@dataclass(frozen=True)
class QueryRecord:
    """One labelled query loaded from ``queries.json``."""

    qid: str
    query: str
    qtype: str
    relevant: List[str]
    notes: str


@dataclass(frozen=True)
class RankerOutcome:
    """One ranker's behaviour on a single query."""

    ranked_urls: List[str]
    precision_at_k: float
    reciprocal_rank: float


def load_queries(path: Path) -> List[QueryRecord]:
    """Read and validate the hand-labelled queries file.

    Args:
        path: Location of ``queries.json``.

    Returns:
        Parsed queries in the order they appear in the file. Empty
        ``relevant_urls`` is permitted (used by the expected-empty case).
    """
    raw = json.loads(path.read_text())
    out: List[QueryRecord] = []
    for entry in raw["queries"]:
        out.append(
            QueryRecord(
                qid=entry["id"],
                query=entry["query"],
                qtype=entry["type"],
                relevant=[r["url"] for r in entry.get("relevant_urls", [])],
                notes=entry.get("notes", ""),
            )
        )
    return out


def candidate_urls(
    index: InvertedIndex, query: str
) -> Tuple[List[str], List[str]]:
    """Return ``(candidates, scoring_terms)`` for ``query`` using the live parser.

    Args:
        index: Inverted index to search.
        query: Raw query string, exactly as a user would type it.

    Returns:
        ``candidates`` is the union of every OR-group's matching URLs after
        AND-, phrase-, and NOT-filtering. ``scoring_terms`` is the flat list
        of terms that should drive the ranker score (positives + phrase
        tokens, in the order the parser produced them).
    """
    groups = parse_query(query)
    union: List[str] = []
    seen = set()
    scoring_terms: List[str] = []
    for group in groups:
        if not group.has_positive_anchor():
            continue
        urls, group_terms = _resolve_group(index, group)
        scoring_terms.extend(group_terms)
        for url in sorted(urls):
            if url not in seen:
                seen.add(url)
                union.append(url)
    return union, scoring_terms


def precision_at_k(ranked: List[str], relevant: List[str], k: int) -> float:
    """Return the fraction of the top-``k`` ranked URLs that are in ``relevant``.

    Args:
        ranked: URLs in descending score order.
        relevant: Ground-truth relevant URLs (any order).
        k: Cutoff for the precision computation.

    Returns:
        ``hits / k``. Always 0 when ``relevant`` is empty (the
        expected-empty queries are excluded from averages by the caller).
    """
    if k <= 0 or not relevant:
        return 0.0
    relevant_set = set(relevant)
    hits = sum(1 for url in ranked[:k] if url in relevant_set)
    return hits / k


def reciprocal_rank(ranked: List[str], relevant: List[str]) -> float:
    """Return the reciprocal of the first relevant document's rank, or 0.

    Args:
        ranked: URLs in descending score order.
        relevant: Ground-truth relevant URLs.

    Returns:
        ``1 / rank`` where ``rank`` is 1-indexed. ``0.0`` if no relevant
        URL appears or if ``relevant`` is empty.
    """
    if not relevant:
        return 0.0
    relevant_set = set(relevant)
    for idx, url in enumerate(ranked, start=1):
        if url in relevant_set:
            return 1.0 / idx
    return 0.0


def _rank_with(scores: Dict[str, float]) -> List[str]:
    """Return URLs sorted by ``-score`` then alphabetical for tie-stability."""
    return [url for url, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


def evaluate_query(
    index: InvertedIndex,
    record: QueryRecord,
    *,
    k: int,
    n_docs: int,
    avg_len: float,
    doc_lens: Dict[str, int],
) -> Tuple[RankerOutcome, RankerOutcome]:
    """Score one query with both rankers and return their outcomes.

    Args:
        index: Inverted index.
        record: The query under evaluation.
        k: Cutoff for the precision metric.
        n_docs: ``total_documents(index)``, hoisted to avoid recomputation.
        avg_len: ``average_document_length(index)``, ditto.
        doc_lens: Per-URL token counts from :func:`document_lengths`.

    Returns:
        Tuple of ``(tfidf_outcome, bm25_outcome)``.
    """
    candidates, terms = candidate_urls(index, record.query)
    if not candidates or not terms:
        empty = RankerOutcome([], 0.0, 0.0)
        return empty, empty

    tfidf_scores = {
        url: tfidf_score(index, terms, url, n_docs, doc_lens.get(url, 0))
        for url in candidates
    }
    bm25_scores = {
        url: bm25_score(
            index, terms, url, n_docs, doc_lens.get(url, 0), avg_len
        )
        for url in candidates
    }

    tfidf_ranked = _rank_with(tfidf_scores)
    bm25_ranked = _rank_with(bm25_scores)

    return (
        RankerOutcome(
            tfidf_ranked,
            precision_at_k(tfidf_ranked, record.relevant, k),
            reciprocal_rank(tfidf_ranked, record.relevant),
        ),
        RankerOutcome(
            bm25_ranked,
            precision_at_k(bm25_ranked, record.relevant, k),
            reciprocal_rank(bm25_ranked, record.relevant),
        ),
    )


def _averages(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def render_markdown_table(
    queries: List[QueryRecord],
    outcomes: List[Tuple[RankerOutcome, RankerOutcome]],
    k: int,
) -> str:
    """Produce the markdown comparison table that the README cites."""
    header = (
        f"| ID  | Query | Type | TF-IDF P@{k} | BM25 P@{k} | TF-IDF MRR | BM25 MRR |\n"
        f"| --- | ----- | ---- | ------------ | ---------- | ---------- | -------- |"
    )
    rows: List[str] = [header]
    for record, (tfidf, bm25) in zip(queries, outcomes):
        rows.append(
            f"| {record.qid} | `{record.query}` | {record.qtype} | "
            f"{tfidf.precision_at_k:.2f} | {bm25.precision_at_k:.2f} | "
            f"{tfidf.reciprocal_rank:.2f} | {bm25.reciprocal_rank:.2f} |"
        )

    scored = [
        (q, t, b) for q, (t, b) in zip(queries, outcomes) if q.relevant
    ]
    rows.append(
        "| **mean (excl. expected-empty)** | | | "
        f"**{_averages([t.precision_at_k for _, t, _ in scored]):.2f}** | "
        f"**{_averages([b.precision_at_k for _, _, b in scored]):.2f}** | "
        f"**{_averages([t.reciprocal_rank for _, t, _ in scored]):.2f}** | "
        f"**{_averages([b.reciprocal_rank for _, _, b in scored]):.2f}** |"
    )
    return "\n".join(rows)


def run(
    *,
    index_path: Path,
    queries_path: Path,
    results_path: Path,
    k: int = DEFAULT_K,
) -> Dict[str, object]:
    """Drive the whole evaluation. Returns the dict that gets written to JSON."""
    index = load_index(str(index_path))
    queries = load_queries(queries_path)

    n_docs = total_documents(index)
    avg_len = average_document_length(index)
    doc_lens = document_lengths(index)

    outcomes = [
        evaluate_query(
            index, record, k=k, n_docs=n_docs, avg_len=avg_len, doc_lens=doc_lens
        )
        for record in queries
    ]

    print(render_markdown_table(queries, outcomes, k))

    serialised = {
        "k": k,
        "corpus": {
            "index_path": str(index_path),
            "documents": n_docs,
            "average_document_length": avg_len,
        },
        "queries": [
            {
                "id": q.qid,
                "query": q.query,
                "type": q.qtype,
                "relevant": q.relevant,
                "notes": q.notes,
                "tfidf": {
                    "ranked_top_k": tfidf.ranked_urls[:k],
                    "precision_at_k": tfidf.precision_at_k,
                    "reciprocal_rank": tfidf.reciprocal_rank,
                },
                "bm25": {
                    "ranked_top_k": bm25.ranked_urls[:k],
                    "precision_at_k": bm25.precision_at_k,
                    "reciprocal_rank": bm25.reciprocal_rank,
                },
            }
            for q, (tfidf, bm25) in zip(queries, outcomes)
        ],
    }

    scored = [
        (t, b) for q, (t, b) in zip(queries, outcomes) if q.relevant
    ]
    serialised["averages"] = {
        "queries_with_judgements": len(scored),
        "tfidf": {
            "mean_precision_at_k": _averages([t.precision_at_k for t, _ in scored]),
            "mean_reciprocal_rank": _averages([t.reciprocal_rank for t, _ in scored]),
        },
        "bm25": {
            "mean_precision_at_k": _averages([b.precision_at_k for _, b in scored]),
            "mean_reciprocal_rank": _averages([b.reciprocal_rank for _, b in scored]),
        },
    }

    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(serialised, indent=2) + "\n")
    return serialised


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index", default=str(ROOT / "data" / "index.json"), type=Path
    )
    parser.add_argument(
        "--queries",
        default=str(ROOT / "evaluation" / "queries.json"),
        type=Path,
    )
    parser.add_argument(
        "--results",
        default=str(ROOT / "evaluation" / "results.json"),
        type=Path,
    )
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    run(
        index_path=Path(args.index),
        queries_path=Path(args.queries),
        results_path=Path(args.results),
        k=args.k,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
