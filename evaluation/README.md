# Evaluation harness — TF-IDF vs BM25

This directory ships a small information-retrieval benchmark that compares
the project's existing TF-IDF ranker against an Okapi BM25 ranker over the
same 202-page crawl of `quotes.toscrape.com`.

## Methodology

1. **Index.** All scoring runs against the committed `data/index.json`. No
   live HTTP traffic is permitted at evaluation time.
2. **Query selection.** `evaluation/queries.json` contains eleven
   hand-labelled queries, sampled to cover five behavioural categories:
   * **single_common** — bare frequent terms (`love`, `life`, `good`).
   * **multi_word** — AND-conjunctions (`tolkien journey`,
     `einstein imagination`, `austen books`).
   * **phrase** — quoted phrases (`"love is"`, `"the truth"`).
   * **rare** — high-IDF terms (`bilbo`, `neruda`).
   * **empty** — a known-absent term (`marx`) that should return nothing.
3. **Relevance judgement.** Each query lists the URLs that a human reader
   considers genuinely relevant, sourced *exclusively* from the index
   (so every entry is reachable by the live retrieval pipeline). Each
   URL carries a one-sentence justification.
4. **Retrieval.** Both rankers receive the same candidate set, produced
   by the project's existing `parse_query` + `_resolve_group` pipeline.
   This isolates *ranking* quality from *retrieval* quality — every
   metric difference between the rankers is purely a property of how
   candidates are ordered.
5. **Metrics.**
   * **Precision\@5 (`P@5`)** — fraction of the top-5 ranked URLs that
     are in the relevant set.
   * **Mean Reciprocal Rank (`MRR`)** — `1 / rank` of the first relevant
     URL, averaged across queries with at least one relevant judgement.
   The expected-empty query (`marx`) is excluded from the mean rows;
   its purpose is to verify that both rankers correctly surface
   nothing.

Run the harness from the repository root:

```bash
python -m evaluation.evaluate
```

The script writes a fresh `evaluation/results.json` and prints the
markdown table reproduced below.

## Limitations

* **Sample size.** Eleven queries is small. The averages should be read
  as a directional signal, not a statistically significant claim.
* **Single annotator.** All relevance judgements were authored by one
  reader of the live site; no inter-annotator-agreement is reported.
* **Static corpus.** The benchmark is locked to a single 202-page
  snapshot. It does not exercise behaviour on much larger or
  multi-domain corpora where BM25's saturation parameters would have
  more to chew on.
* **Tie-breaking.** Equal scores fall back to alphabetical URL order,
  which is reproducible but artificial.

## Latest results

```
| ID  | Query | Type | TF-IDF P@5 | BM25 P@5 | TF-IDF MRR | BM25 MRR |
| --- | ----- | ---- | ---------- | -------- | ---------- | -------- |
| q01 | `love`                  | single_common | 0.00 | 0.20 | 0.12 | 1.00 |
| q02 | `life`                  | single_common | 0.20 | 0.40 | 0.50 | 1.00 |
| q03 | `good`                  | single_common | 0.20 | 0.20 | 0.50 | 0.50 |
| q04 | `tolkien journey`       | multi_word    | 0.60 | 0.60 | 1.00 | 1.00 |
| q05 | `einstein imagination`  | multi_word    | 0.20 | 0.20 | 1.00 | 1.00 |
| q06 | `austen books`          | multi_word    | 0.40 | 0.40 | 1.00 | 1.00 |
| q07 | `"love is"`             | phrase        | 0.00 | 0.00 | 0.12 | 0.17 |
| q08 | `"the truth"`           | phrase        | 0.20 | 0.20 | 0.33 | 0.25 |
| q09 | `bilbo`                 | rare          | 0.40 | 0.40 | 1.00 | 1.00 |
| q10 | `neruda`                | rare          | 0.20 | 0.20 | 1.00 | 1.00 |
| q11 | `marx`                  | empty         |  —   |  —   |  —   |  —   |
| **mean (excluding marx)**     |               | **0.24** | **0.28** | **0.66** | **0.79** |
```

### Observations

* **BM25 wins on common terms.** The largest differential is on `love`
  (q01) and `life` (q02), where BM25's length normalisation pushes the
  focused tag pages above the homepage and miscellaneous listing
  pages. Pure TF-IDF rewards homepages that mention the term once for
  every navigation link.
* **Rankers tie on rare or sharp queries.** For `tolkien journey`,
  `bilbo`, and `neruda` both rankers converge — the candidate set is
  small and the IDF weight dominates either formulation.
* **Phrase queries are noisy.** `"love is"` and `"the truth"` both
  retrieve dense tag pages where the relevant quotes are diluted by
  the per-page sidebar; here neither ranker has enough signal to
  separate hits from near-misses.
* **Expected-empty behaves correctly.** Both rankers return zero
  results for `marx`, validating the retrieval pipeline rather than
  the ranking step.

## Files

* `queries.json` — eleven hand-labelled queries with justifications.
* `evaluate.py` — reproducible harness.
* `results.json` — most-recent run's full output (full top-K lists,
  per-query metrics, corpus statistics).
