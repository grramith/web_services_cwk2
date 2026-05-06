# Quotes Search Engine

A command-line search engine that crawls
[quotes.toscrape.com](https://quotes.toscrape.com/), builds an inverted index
of every page it visits, and answers user queries from an interactive shell.

Coursework submission for **COMP3011 Web Services and Web Data**, University
of Leeds, 2025/26.

---

## Overview

The tool is a small REPL with four commands:

| Command          | Effect                                                                 |
| ---------------- | ---------------------------------------------------------------------- |
| `build`          | Crawl the site (politely!) and build a fresh inverted index on disk.   |
| `load`           | Load a previously saved index from `data/index.json`.                  |
| `print <word>`   | Show the index entry (URLs, frequency, positions) for a single word.   |
| `find <query>`   | Search. Multi-word queries use AND semantics, ranked by TF-IDF.        |
| `help`           | List the available commands.                                           |
| `exit` / `quit`  | Leave the shell. `Ctrl-D` and `Ctrl-C` work too.                       |

---

## Architecture

The codebase is deliberately split into single-responsibility modules so
each one can be unit-tested in isolation:

```
src/
├── config.py    constants (politeness delay, base URL, default paths, UA)
├── crawler.py   polite BFS crawler with error handling
├── indexer.py   HTML → text → tokens → inverted index (freq + positions)
├── storage.py   JSON persistence of the inverted index
├── search.py    print_word + TF-IDF ranked find
└── main.py      interactive REPL that wires everything together
```

The data flow is one-way: `crawler → indexer → storage` for index creation,
and `storage → search` at query time.

### Module summary

* **[src/crawler.py](src/crawler.py)** — `Crawler.crawl(start_url)` performs a
  breadth-first traversal of the site. It enforces a 6-second sleep between
  requests, sends a custom `User-Agent`, follows only links inside
  `quotes.toscrape.com`, drops fragments, deduplicates visited URLs, and
  swallows per-page failures (timeouts, connection errors, non-200 responses)
  so a single bad page never aborts the whole run. Misuse — e.g. starting a
  crawl outside the allowed domain — raises a custom `CrawlError`.

* **[src/indexer.py](src/indexer.py)** — `Indexer.build_index({url: html})`
  produces a nested dict of the form
  `{word: {url: {frequency, positions}}}`. Two pure helpers, `extract_text`
  and `tokenize`, do the HTML cleanup and tokenisation respectively, and are
  unit-tested directly.

* **[src/storage.py](src/storage.py)** — `save_index` / `load_index` round-trip
  the index through pretty-printed UTF-8 JSON. A custom `IndexNotFoundError`
  (subclass of `FileNotFoundError`) gives a clear message when the index file
  is missing.

* **[src/search.py](src/search.py)** — `print_word` formats one term's entry
  for the user; `find` tokenises the query, intersects per-term URL sets
  (AND semantics), and ranks the survivors by summed TF-IDF.

* **[src/main.py](src/main.py)** — REPL dispatcher. Errors from any handler
  are caught and surfaced as friendly messages; `Ctrl-D`/`Ctrl-C` exit
  cleanly.

---

## Installation

Python 3.9+ is required (the codebase uses `from __future__ import
annotations` for type hints).

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Dependencies

| Package          | Why                                                |
| ---------------- | -------------------------------------------------- |
| `requests`       | HTTP client used by the crawler.                   |
| `beautifulsoup4` | HTML parsing for link extraction and text cleanup. |
| `pytest`         | Test runner.                                       |
| `pytest-cov`     | Coverage reporting.                                |

---

## Usage

Start the shell:

```bash
python -m src.main
```

Example session:

```
$ python -m src.main
Quotes search engine. Type 'help' for commands, 'exit' to quit.
> build
Crawling https://quotes.toscrape.com/ (this respects a 6-second politeness window)...
Fetched 50 page(s). Building index...
Index built (1832 unique terms) and saved to data/index.json.
> find good friends
3 result(s) for 'good friends' (ranked by TF-IDF):
  1. https://quotes.toscrape.com/page/3/
  2. https://quotes.toscrape.com/tag/friends/
  3. https://quotes.toscrape.com/
> print einstein
'einstein' appears in 5 document(s):
  https://quotes.toscrape.com/
    frequency: 1
    positions: [37]
  ...
> exit
```

A subsequent session can skip the crawl by using `load`:

```
> load
Loaded index with 1832 term(s) from data/index.json.
> find world
...
```

---

## Testing

```bash
pytest --cov=src tests/
```

The full suite uses **only mocked HTTP** — no network calls during tests,
which means it runs in a fraction of a second and is safe to run repeatedly
without hammering the live site.

Test layout:

| File                          | Covers                                                        |
| ----------------------------- | ------------------------------------------------------------- |
| `tests/test_crawler.py`       | Politeness, link filtering, dedup, fragment handling, errors. |
| `tests/test_indexer.py`       | Tokenisation rules, position tracking, multi-page aggregation.|
| `tests/test_storage.py`       | JSON round-trip, missing-file handling, Unicode safety.       |
| `tests/test_search.py`        | `print_word`, AND queries, TF-IDF ranking, case insensitivity.|
| `tests/test_integration.py`   | Full pipeline crawl → index → save → load → find.             |

---

## Design rationale

### Why a 6-second politeness window?

The brief mandates a minimum of six seconds between hits to
`quotes.toscrape.com`. The constant lives in
[src/config.py](src/config.py) as `POLITENESS_DELAY_SECONDS` and the
`Crawler` constructor refuses any value lower than that, so the floor is
enforced at construction time rather than inferred at runtime.

### Why a nested dict for the inverted index?

```python
{ word: { url: { "frequency": int, "positions": [int, ...] } } }
```

Storing per-document statistics (not just a list of URLs) is a hard
requirement of the brief, but it also makes ranking and future features
much easier. The structure has three nice properties:

1. **O(1) lookup** of any term's posting list.
2. **All the statistics live together** — TF for ranking, positions for
   future phrase queries — so `find` and `print` need no joins.
3. **Maps cleanly to JSON**, which is what we persist anyway.

The same information could be stored in a more compact columnar form
(e.g. parallel lists), but the dict form trades a small amount of size
for a lot of readability when grading the artifact.

### Why JSON instead of pickle?

* **Portable.** Any language can read it; the marker can open it in a text
  editor and inspect it directly.
* **Safe.** Loading pickle from an untrusted source executes arbitrary
  code; loading JSON does not.
* **Diff-friendly.** Pretty-printed JSON shows up usefully in version
  control.

The trade-off — JSON is bulkier than a binary pickle — is negligible at
the scale of `quotes.toscrape.com` (a few thousand terms).

### Why TF-IDF ranking?

TF-IDF is the canonical bag-of-words ranking algorithm and a natural fit
for the data we already collect: term frequency *per document* is exactly
what the index stores, and document frequency falls out of `len(posting)`.

The implementation uses the formula stated in the brief:

* `tf(t, d) = freq(t, d) / total_tokens(d)`
* `idf(t)   = log(N / df(t))`
* multi-term queries sum the per-term TF-IDF scores

Ties are broken by URL alphabetical order so results are deterministic
(important for testability). One known limitation of the un-smoothed IDF
is that a term appearing in *every* document scores zero — the tests
document this and the README is honest about it. A smoothed variant
(`log((N+1)/(df+1)) + 1`, sklearn-style) would avoid this, but using the
formula as stated keeps the implementation faithful to the brief.

### Why a separate `storage.py`?

Keeping persistence out of the indexer means the indexing algorithm has
no opinion about *where* its output ends up. Swapping JSON for SQLite or
Redis would only require rewriting `storage.py` — `indexer.py` and
`search.py` would be untouched.

---

## Repository layout

```
.
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── crawler.py
│   ├── indexer.py
│   ├── main.py
│   ├── search.py
│   └── storage.py
├── tests/
│   ├── __init__.py
│   ├── test_crawler.py
│   ├── test_indexer.py
│   ├── test_integration.py
│   ├── test_search.py
│   └── test_storage.py
├── data/
│   └── (index.json — produced by `build`, gitignored)
├── requirements.txt
├── README.md
└── .gitignore
```
