# COMP3011 CWK2 — Phase 3 Plan

## Live-crawl verification

The committed `data/index.json` was produced by a single full polite crawl of
`https://quotes.toscrape.com/`. Numbers below are derived from the artefact in
the working tree on the current branch — no fresh HTTP traffic is permitted at
this stage of the project.

| Metric | Value | Source |
| --- | --- | --- |
| Pages indexed | **202** | distinct URLs across all postings in `data/index.json` |
| Unique terms | **4574** | top-level keys in `data/index.json` |
| Index file size | **2,796,791 bytes** (≈2.67 MiB / 2.8 MB) | `stat data/index.json` |
| Build wall-clock (lower bound) | **≥ 20 min 12 s** | 202 fetches × 6 s politeness window + fetch/parse overhead; the previous live build was completed at the file's mtime (`2026-05-09 20:18:11`) |
| Cold load time | **0.076 s** | `load_index('data/index.json')` timed with `time.perf_counter` |
| `find good` | **30 result(s)** | full TF-IDF result list captured below |
| `find "good night"` | **No results** | exact phrase not found at consecutive positions in any document |

### `find good` output (30 result(s) for 'good', ranked by TF-IDF)

```
  1. https://quotes.toscrape.com/tag/contentment/
  2. https://quotes.toscrape.com/tag/good/
  3. https://quotes.toscrape.com/tag/aliteracy/
  4. https://quotes.toscrape.com/tag/classic/
  5. https://quotes.toscrape.com/tag/alcohol/
  6. https://quotes.toscrape.com/tag/integrity/
  7. https://quotes.toscrape.com/tag/friendship/
  8. https://quotes.toscrape.com/tag/music/
  9. https://quotes.toscrape.com/tag/friends/
 10. https://quotes.toscrape.com/tag/books/
 11. https://quotes.toscrape.com/tag/attributed-no-source/
 12. https://quotes.toscrape.com/tag/writing/
 13. https://quotes.toscrape.com/tag/life/
 14. https://quotes.toscrape.com/page/7/
 15. https://quotes.toscrape.com/page/2/
 16. https://quotes.toscrape.com/tag/heartbreak/
 17. https://quotes.toscrape.com/tag/sisters/
 18. https://quotes.toscrape.com/
 19. https://quotes.toscrape.com/page/6/
 20. https://quotes.toscrape.com/tag/humor/
 21. https://quotes.toscrape.com/author/Albert-Einstein
 22. https://quotes.toscrape.com/page/3/
 23. https://quotes.toscrape.com/author/Terry-Pratchett
 24. https://quotes.toscrape.com/page/9/
 25. https://quotes.toscrape.com/author/George-Eliot
 26. https://quotes.toscrape.com/tag/inspirational/
 27. https://quotes.toscrape.com/author/J-R-R-Tolkien
 28. https://quotes.toscrape.com/author/Ralph-Waldo-Emerson
 29. https://quotes.toscrape.com/author/J-K-Rowling
 30. https://quotes.toscrape.com/tag/love/
```

### `find "good night"` output

```
No results.
```

The phrase `good night` is not present at consecutive token positions on any
crawled page — `quotes.toscrape.com` simply does not host that exact phrase.
This is a true negative, not a parser bug: the phrase-search code-path (see
`src/search.py::_has_phrase_at`) verifies adjacency from the `positions` lists
captured at index time, and the same lists are confirmed populated by the
inverted-index unit tests.

### How to reproduce

```bash
python -c "import json; d=json.load(open('data/index.json')); \
  urls=set(); [urls.update(p) for p in d.values()]; \
  print(len(urls), 'pages,', len(d), 'terms')"

stat -f "%z bytes" data/index.json

printf 'load\nfind good\nexit\n'              | python -m src.main
printf 'load\nfind \"good night\"\nexit\n'    | python -m src.main
```

## Phase 3 task ledger

The plan below mirrors the protocol used in this branch: every task lives on
its own `feat/`, `docs/`, or `test/` branch, ships with green tests at ≥ 90 %
coverage, and lands on `main` via `git merge --no-ff`.

| ID  | Task                                            | Status   |
| --- | ----------------------------------------------- | -------- |
| —   | Live-crawl verification (this section)          | done     |
| T1  | TF-IDF vs BM25 precision\@k harness             | pending  |
| T2  | Result snippets with highlighting               | pending  |
| T3  | Benchmarking harness                            | pending  |
| T4  | GitHub Actions CI + coverage badge              | pending  |
| T5  | Performance regression test                     | pending  |
| T6  | Expand Complexity section                       | pending  |
| T7  | References (academic + tools)                   | pending  |
| T8  | Optional NLTK PorterStemmer                     | pending  |
| T9  | Google-style docstrings for the eight remainers | pending  |
| T11 | Annotated tag `v1.0` (no push)                  | pending  |

### Hard rules carried over from earlier phases

* No new live HTTP requests — everything mocked or driven from the cached
  `data/index.json`.
* Politeness window stays at ≥ 6 s in any code path that *could* talk to the
  live site.
* No history rewrites on the existing commits — no rebase / squash / amend /
  force-push.
* Coverage floor is 90 %.
* The only new third-party dependency permitted is `nltk` (for the optional
  Porter stemmer in T8).
