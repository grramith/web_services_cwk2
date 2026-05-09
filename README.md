# Quotes Search Engine

[![tests](https://github.com/grramith/web_services_cwk2/actions/workflows/tests.yml/badge.svg)](https://github.com/grramith/web_services_cwk2/actions/workflows/tests.yml)
[![coverage](https://img.shields.io/badge/coverage-95%25-brightgreen)](./README.md#testing)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](./.github/workflows/tests.yml)

A command-line search engine that crawls [quotes.toscrape.com](https://quotes.toscrape.com/), builds an inverted index of the pages it visits, and answers user queries through an interactive shell.

Coursework submission for **COMP3011 Web Services and Web Data**, University of Leeds, 2025/26.

## Contents

- [Project Overview](#project-overview)
- [Architecture](#architecture-overview)
- [Installation](#installation)
- [Usage](#usage-examples)
- [Inverted Index Design](#inverted-index-design)
- [TF-IDF Ranking](#tf-idf-ranking)
- [Complexity](#complexity)
- [Benchmarks](#benchmarks)
- [Testing](#testing)
- [GenAI Declaration](#genai-declaration-and-reflection)
- [References](#references-and-resources)

## Project Overview

This project implements a small search engine pipeline. It crawls pages from the target website, extracts text from the HTML, tokenises the content, builds an inverted index, saves the index to disk, and allows the user to search it through a command-line interface.

The project follows the main stages of a search engine:

1. **Crawling**: collect pages from the target site while respecting a politeness delay.
2. **Indexing**: convert HTML into tokens and store word occurrences in an inverted index.
3. **Retrieval**: answer user queries using the index and rank results using TF-IDF.

The tool is designed for the coursework target website:

```text
https://quotes.toscrape.com/
```

## Main Features

- Crawls `https://quotes.toscrape.com/`
- Enforces a minimum 6-second politeness delay between requests
- Builds an inverted index of word occurrences
- Stores document-level frequency and token positions for each word
- Saves and loads the index from `data/index.json`
- Supports case-insensitive search
- Provides an interactive command-line shell
- Supports the required `build`, `load`, `print`, and `find` commands
- Supports single-word and multi-word queries
- Ranks search results using TF-IDF
- Supports phrase search using stored token positions
- Supports basic Boolean query processing
- Provides spelling suggestions for missing terms
- Handles common errors with user-friendly messages
- Includes an automated test suite using mocked HTTP requests

## Command Summary

| Command | Purpose |
| ------- | ------- |
| `build [max_pages]` | Crawl the site, build a fresh index, and save it to disk. The optional page cap is useful for short demonstrations. |
| `load` | Load a previously saved index from `data/index.json`. |
| `print <word>` | Show the index entry for a single word, including URLs, frequency, and positions. |
| `find <query>` | Search the index. Results are ranked by TF-IDF. |
| `help` | Show the available commands. |
| `exit` or `quit` | Leave the shell. `Ctrl-D` and `Ctrl-C` also exit cleanly. |

## Repository Structure

```text
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
│   ├── test_main.py
│   ├── test_search.py
│   └── test_storage.py
├── data/
│   ├── .gitkeep            # committed, preserves the directory
│   └── index.json          # produced by `build`, gitignored
├── requirements.txt
├── README.md
└── .gitignore
```

## Architecture Overview

The codebase is split into single-responsibility modules. This makes the system easier to understand, test, and explain.

```text
src/
├── config.py    shared constants such as base URL, politeness delay, and default paths
├── crawler.py   polite breadth-first crawler with error handling
├── indexer.py   HTML cleanup, tokenisation, and inverted index construction
├── storage.py   JSON save and load functions
├── search.py    print, find, TF-IDF ranking, Boolean queries, and suggestions
└── main.py      interactive command-line shell
```

The data flow during index construction is:

```text
crawler -> indexer -> storage
```

At query time, the data flow is:

```text
storage -> search -> command-line output
```

This separation means each part of the tool has a clear responsibility. The crawler does not know how ranking works, the indexer does not know how the command-line shell works, and the search module does not need to fetch live web pages.

## Module Summary

### `src/crawler.py`

The crawler performs a breadth-first traversal of `quotes.toscrape.com`. It follows only links inside the allowed domain and avoids repeatedly visiting the same URL.

The crawler also:

- enforces the 6-second politeness delay
- sends a custom `User-Agent`
- removes URL fragments
- skips unsuitable or repeated URLs
- handles timeouts and failed responses
- continues crawling if one page fails

This design makes the crawler polite and robust. A single bad page should not stop the whole indexing process.

### `src/indexer.py`

The indexer converts page HTML into clean text, tokenises the text, and builds the inverted index.

The main index structure is:

```python
{
    "word": {
        "url": {
            "frequency": 2,
            "positions": [12, 47]
        }
    }
}
```

This structure stores more than a list of URLs. It records how often a word appears in each page and where it appears. That is important because the coursework requires the index to store word statistics such as frequency and position.

### `src/storage.py`

The storage module saves and loads the index as JSON.

JSON was used because it is:

- easy to inspect
- portable
- safer than pickle
- suitable for the size of this coursework dataset

The saved index is written to:

```text
data/index.json
```

### `src/search.py`

The search module handles query processing and result ranking. It provides the logic behind the `print` and `find` commands.

It supports:

- printing a word's full index entry
- single-word search
- multi-word search
- phrase search
- basic Boolean query handling
- TF-IDF ranking
- spelling suggestions for failed queries

### `src/main.py`

The main module provides the interactive shell. It reads commands from the user, calls the correct function, and prints clear output.

It also handles invalid commands and exits cleanly when the user types `exit`, types `quit`, presses `Ctrl-D`, or presses `Ctrl-C`.

## Installation

Python 3.9 or newer is recommended.

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install the required packages:

```bash
pip install -r requirements.txt
```

## Dependencies

| Package | Purpose |
| ------- | ------- |
| `requests` | Sends HTTP requests in the crawler. |
| `beautifulsoup4` | Parses HTML and extracts links/text. |
| `pytest` | Runs the automated tests. |
| `pytest-cov` | Produces coverage reports. |

## Running the Tool

Start the interactive shell with:

```bash
python -m src.main
```

You should see:

```text
Quotes search engine. Type 'help' for commands, 'exit' to quit.
>
```

## Usage Examples

### Build the Index

```text
> build 5
Crawling https://quotes.toscrape.com/ (capped at 5 pages). A 6-second politeness delay runs between every request, so the full site takes a few minutes. Progress prints below.
  [1] fetched https://quotes.toscrape.com/
  [2] fetched https://quotes.toscrape.com/author/Albert-Einstein
  [3] fetched https://quotes.toscrape.com/tag/change/
  [4] fetched https://quotes.toscrape.com/tag/deep-thoughts/
  [5] fetched https://quotes.toscrape.com/tag/thinking/
Fetched 5 page(s). Building index...
Index built (464 unique terms) and saved to data/index.json.
```

The optional number after `build` limits the crawl. This is useful for quick testing and video demonstrations.

For the full submission run, use:

```text
> build
```

### Load a Saved Index

```text
> load
Loaded index with 464 term(s) from data/index.json.
```

This avoids crawling the website again if an index has already been built.

### Print a Word Entry

```text
> print love
'love' appears in 4 document(s):
  https://quotes.toscrape.com/
    frequency: 2
    positions: [198, 274]
  https://quotes.toscrape.com/tag/change/
    frequency: 1
    positions: [44]
  https://quotes.toscrape.com/tag/deep-thoughts/
    frequency: 1
    positions: [45]
  https://quotes.toscrape.com/tag/thinking/
    frequency: 1
    positions: [77]
```

This command shows that the index stores frequency and token positions.

### Search for One Word

```text
> find love
4 result(s) for 'love' (ranked by TF-IDF):
  1. https://quotes.toscrape.com/tag/change/
  2. https://quotes.toscrape.com/tag/deep-thoughts/
  3. https://quotes.toscrape.com/tag/thinking/
  4. https://quotes.toscrape.com/
```

### Search for Multiple Words

```text
> find good friends
1 result(s) for 'good friends' (ranked by TF-IDF):
  1. https://quotes.toscrape.com/
```

Multi-word queries use AND-style matching by default. This means all query terms must appear in the returned page.

### Phrase Search

```text
> find "good friends"
Phrase search: "good friends"
1 result(s) (ranked by TF-IDF):
  1. https://quotes.toscrape.com/
```

Phrase search uses the stored token positions to check that words appear next to each other in the correct order.

### Boolean Query Example

```text
> find love AND life
Boolean query: love AND life
4 result(s) (ranked by TF-IDF):
  1. https://quotes.toscrape.com/tag/change/
  2. https://quotes.toscrape.com/tag/deep-thoughts/
  3. https://quotes.toscrape.com/tag/thinking/
  4. https://quotes.toscrape.com/
```

The Boolean logic is based on document sets:

| Operator | Meaning |
| -------- | ------- |
| `AND` | Return pages containing both terms. |
| `OR` | Return pages containing either term. |
| `NOT` | Exclude pages containing the term after `NOT`. |

Uppercase `AND`, `OR`, and `NOT` are treated as operators. Lowercase words such as `and` are treated as normal query terms.

### Spelling Suggestions

If the user searches for a word that is not in the index, the tool suggests close matches from the indexed vocabulary.

```text
> print lvoe
'lvoe' is not in the index. Did you mean: love, live?
```

This is useful for simple typing errors and improves the user experience.

### Invalid Commands

```text
> laod
Unknown command: 'laod'. Type 'help' for the list.
```

The shell handles invalid commands without crashing.

## Inverted Index Design

The inverted index is a nested dictionary. The outer key is the token. The inner key is the URL where that token appears.

```python
{
    "love": {
        "https://quotes.toscrape.com/": {
            "frequency": 2,
            "positions": [198, 274]
        },
        "https://quotes.toscrape.com/tag/change/": {
            "frequency": 1,
            "positions": [44]
        }
    }
}
```

This design was chosen for three reasons.

First, dictionary lookup gives fast average-case access to a word's posting list.

Second, frequency and positions are stored together. This supports both the required `print` command and more advanced features such as TF-IDF ranking and phrase search.

Third, the structure maps clearly to JSON, so the saved index is easy to inspect.

The main trade-off is that storing positions increases the size of the index. For this coursework dataset, that is acceptable because the site is small and the extra information improves the quality of the search tool.

## Tokenisation

The tokeniser normalises text before adding it to the index.

It:

- converts text to lowercase
- removes punctuation
- handles common Unicode punctuation
- splits text into tokens
- keeps stopwords

Keeping stopwords means queries such as `find the` and `print the` still work. This keeps the tool simple and predictable for demonstration.

## TF-IDF Ranking

The `find` command ranks results using TF-IDF.

TF-IDF gives higher scores to words that are frequent in a specific document but less common across the whole collection. This is more useful than returning matching pages in an arbitrary order.

The implementation uses:

```text
tf(t, d) = freq(t, d) / total_tokens(d)
idf(t) = log(N / df(t))
```

Where:

- `freq(t, d)` is the number of times term `t` appears in document `d`
- `total_tokens(d)` is the total number of indexed tokens in document `d`
- `N` is the number of indexed documents
- `df(t)` is the number of documents containing term `t`

For multi-word queries, the per-term scores are summed. Results are then sorted by score. Ties are broken alphabetically by URL so the output is deterministic and testable.

## Query Processing

The search system supports several query types.

### Plain Queries

```text
find good friends
```

This is treated as:

```text
good AND friends
```

Only documents containing both words are returned.

### Phrase Queries

```text
find "good friends"
```

The engine first finds documents containing all words in the phrase. It then checks the token positions to confirm that the words appear next to each other in order.

### Boolean Queries

```text
find love AND life
find love OR hate
find love NOT hate
```

Boolean queries are handled using set operations over matching document URLs.

This design is simple, explainable, and efficient for the size of the indexed collection.

## Complexity

The asymptotic costs below are stated in terms of a fixed set of
parameters, defined once here so the table can be read without guessing.

| Symbol | Meaning |
| ------ | ------- |
| `n` | Number of characters in a single document. |
| `P` | Number of pages (documents) in the indexed corpus. |
| `L` | Mean tokens per page after tokenisation. |
| `t` | Number of query terms in a single user query (positives + phrase tokens). |
| `p` | Number of candidate documents — i.e. those containing every positive term in the query. |
| `m` | Mean position-list length per term — the average number of times a term occurs in a document that contains it. |
| `I` | Size of the persisted JSON index in bytes. |

With those symbols fixed, the costs are:

| Operation | Worst-case complexity | Explanation |
| --------- | --------------------- | ----------- |
| Tokenisation of one page | `O(n)` | The page text is scanned once and split on whitespace after a `str.translate` punctuation pass. |
| Building the inverted index | `O(P · L)` | Every token of every page is dispatched into a `setdefault`-backed dictionary, doing constant work per token. |
| Single-term posting lookup | `O(1)` expected | Direct hash-table access on the term key. |
| Multi-term AND retrieval | `O(t · p)` | The smallest posting is intersected against the rest; the overall work is bounded by `t` set intersections each touching at most `p` URLs. |
| Phrase verification | `O(p · t · m)` | For each of the `p` candidates we walk the `t` position lists in lockstep; on average each list has `m` entries. |
| TF-IDF or BM25 scoring | `O(t · p)` | One score evaluation per (query-term, candidate) pair, plus an `O(p · log p)` sort to order the results — sorting is the dominant cost only when `p ≫ t`. |
| Did-you-mean suggestion | `O(V)` | `difflib.get_close_matches` scans the entire vocabulary `V` for one missed term, but only when retrieval returns zero hits. |
| Persisting / loading the index | `O(I)` | The whole JSON document is streamed by the standard library; the constant factors are dominated by JSON parsing, not by Python-level work. |

The crawler is intentionally slower than the indexing and search logic
because it must respect the required 6-second politeness delay; its
wall-clock cost is `≥ 6 · P` seconds and is independent of the symbols
above.

## Benchmarks

The numbers below come from `python -m benchmarks.run_benchmarks`, run on the
committed `data/index.json` (4 574 terms / 202 pages / 2 796 791 bytes). The
harness is deterministic — the build measurement uses a seeded synthetic
fixture so reruns produce stable numbers, and the query measurement samples 50
distinct vocabulary terms from the same RNG seed.

| Measurement | Value | Notes |
| --- | --- | --- |
| Build (synthetic fixture) | **11.22 ms** | 50 pages, 12 600 tokens |
| Load `data/index.json` | **16.90 ms** | 4 574 terms |
| Mean query (warm) | **1.459 ms** | median 0.804 ms / max 7.771 ms over 50 terms |
| Index size on disk | **2 731.2 KiB** | 2 796 791 bytes |

A single warm-up call is discarded from the query timings so import-time and
first-touch cache effects do not skew the average. The full report (including
the median and max) is persisted to `benchmarks/results.json`.

Reproduce with:

```bash
python -m benchmarks.run_benchmarks
```

## Testing

Run the test suite with:

```bash
pytest
```

To run the tests with coverage:

```bash
pytest --cov=src tests/ --cov-report=term-missing
```

The current run reports **107 passing tests** with **94% line coverage** across `src/`. Per-module coverage is `crawler.py` 97%, `indexer.py` 100%, `search.py` 94%, `storage.py` 100%, `main.py` 88%, `config.py` 100%.

The test suite uses mocked HTTP requests. This means the tests do not contact the live website and do not wait for the 6-second politeness delay. Instead, the tests check that the delay function is called correctly.

## Testing Strategy

The tests cover the main system components.

| Test File | Main Coverage |
| --------- | ------------- |
| `tests/test_crawler.py` | Politeness delay, link filtering, URL handling, duplicate prevention, and crawler errors. |
| `tests/test_indexer.py` | Text extraction, tokenisation, case handling, frequency counts, and token positions. |
| `tests/test_storage.py` | JSON save/load behaviour, missing file handling, and Unicode safety. |
| `tests/test_search.py` | `print_word`, single-word search, multi-word search, Boolean queries, TF-IDF ranking, suggestions, and case-insensitive search. |
| `tests/test_integration.py` | Full pipeline behaviour from crawl to index to save/load to search. |
| `tests/test_main.py` | Command dispatch, invalid commands, and shell exit behaviour. |

The current test suite contains 107 passing tests with 94% line coverage. This provides evidence that the main functionality and edge cases are covered.

## Error Handling

The tool is designed to fail gracefully.

Examples include:

- Missing index file
- Invalid commands
- Empty queries
- Misspelled words
- Failed HTTP requests
- Non-200 HTTP responses
- Repeated or unsuitable URLs

Instead of crashing, the program prints clear messages to the user where possible.

## Known Limitations

This project is designed for the coursework website rather than the whole web.

The main limitations are:

- The crawler only follows links inside `quotes.toscrape.com`.
- The 6-second politeness delay means a full crawl takes several minutes.
- The index is stored as JSON, which is readable but not as efficient as a database for much larger collections.
- TF-IDF is a simple ranking method and does not consider link authority or semantic meaning.
- Boolean query handling is intentionally basic and is not designed for deeply nested expressions.
- The system is single-process. A larger crawler would need stronger rate-limiting and queue management.

These limitations are acceptable for the coursework scope because the goal is to demonstrate crawling, indexing, retrieval, testing, and design understanding.

## GenAI Declaration and Reflection


This project was developed with assistance from Anthropic's Claude,
accessed through the Claude Code CLI tool. The assistant was used to
help draft module skeletons, generate unit tests, refine error
handling, edit documentation, and discuss design trade-offs. Every
suggestion was reviewed, run locally, and adapted before being
committed. Specific design choices were owned by the author, including
the decision to keep stopwords in the index, to verify phrases
positionally rather than treating them as multi-word AND queries, to
recognise boolean operators only when uppercase, and to use a 0.7
similarity cutoff for did-you-mean suggestions.

The coursework brief recommends the University's secure Copilot access; this project used Claude Code instead, and no personal data, university credentials, or unpublished work beyond this repository's contents was shared with the assistant.

Working with the assistant was most useful for:

* Writing dense unit tests, where naming conventions and parametrised
  cases are easy to forget but mechanically generated well.
* Catching small consistency issues across modules (for example,
  shared error messages, docstring style).
* Surfacing edge cases that benefited from explicit tests (Unicode
  punctuation, `/page/1/` canonicalisation, BeautifulSoup parse
  failures).

The assistant was less useful when the answer required understanding
the live site's quirks. URL aliasing on `quotes.toscrape.com`, the
exact User-Agent the brief expected, and the practical pace of a
six-second crawl were all things the author had to inspect and
verify directly. The author also drove the testing of the live site
manually so that the smoke-tested behaviour matched what the test
suite asserts.

In summary, AI assistance accelerated the boilerplate-heavy parts of
the work (test writing, documentation editing, module scaffolding).
Algorithmic and architectural decisions were discussed before being
implemented, and every commit reflects a change that was verified to
pass the test suite locally.

## References and Resources

- COMP3011 Coursework 2 Brief
- Python Requests documentation
- Beautiful Soup documentation
- pytest documentation
- pytest-cov documentation
- Quotes to Scrape website