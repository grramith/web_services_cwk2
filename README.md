# Quotes Search Engine

A command-line search engine that crawls
[quotes.toscrape.com](https://quotes.toscrape.com/), builds an inverted
index of every page it visits, and answers user queries from an
interactive shell.

Coursework submission for **COMP3011 Web Services and Web Data**,
University of Leeds, 2025/26.


## Project overview

The tool follows the classic three-stage pipeline of a small search
engine. A polite breadth-first crawler fetches pages from the target
site. An indexer turns the HTML into a nested-dictionary inverted index
that records, for every word, which URLs contain it, how often, and at
which token positions. A query engine then answers user requests
against that index, with results ranked by TF-IDF.

The program is run as an interactive REPL. The available commands are:

| Command | Effect |
| --- | --- |
| `build [max_pages]` | Crawl the site and build a fresh inverted index. The optional cap (e.g. `build 10`) is useful for quick demos. |
| `load` | Load a previously saved index from `data/index.json`. |
| `print <word>` | Show the index entry (URL, frequency, positions) for a single word. |
| `find <query>` | Search. Supports plain AND, quoted phrases, and uppercase boolean operators. |
| `help` | List the available commands. |
| `exit` / `quit` | Leave the shell. `Ctrl-D` and `Ctrl-C` work too. |


## Quick start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

At the `>` prompt:

```
> build 5          # quick demo crawl, ~30 seconds
> find love        # ranked TF-IDF results
> exit
```

A full crawl of the live site takes around five minutes because of the
mandatory six-second politeness delay between requests. Use `build`
without an argument when preparing the submission run.


## Architecture overview

The codebase is split into single-responsibility modules so each one
can be unit-tested in isolation:

```
src/
├── config.py    constants (politeness delay, base URL, default paths, UA)
├── crawler.py   polite BFS crawler with error handling
├── indexer.py   HTML to text to tokens to inverted index
├── storage.py   JSON persistence of the inverted index
├── search.py    print_word, find, parse_query, suggestions
└── main.py      interactive REPL that wires everything together
```

Data flows in one direction. During index construction the path is
`crawler` to `indexer` to `storage`. At query time the path is
`storage` to `search`, and the REPL never has to reach back into the
crawler.

### Module summary

* **[src/crawler.py](src/crawler.py).** `Crawler.crawl(start_url)`
  performs a breadth-first traversal of the site. It enforces a
  six-second sleep between requests, sends a custom `User-Agent`,
  follows only links inside `quotes.toscrape.com`, drops fragments,
  collapses `/page/1/` aliases onto the bare path, skips non-content
  URLs such as `/login` and `/logout`, deduplicates visited URLs, and
  swallows per-page failures (timeouts, connection errors, non-200
  responses, BeautifulSoup parse errors) so a single bad page never
  aborts the whole run. Misuse, for example starting a crawl outside
  the allowed domain, raises a custom `CrawlError`.

* **[src/indexer.py](src/indexer.py).**
  `Indexer.build_index({url: html})` produces a nested dictionary of
  the form `{word: {url: {frequency, positions}}}`. Two pure helpers,
  `extract_text` and `tokenize`, do the HTML cleanup and tokenisation
  respectively, and are unit-tested directly. The tokeniser handles
  Unicode punctuation found on the live site (smart quotes, em dashes,
  ellipses, non-breaking spaces).

* **[src/storage.py](src/storage.py).** `save_index` and `load_index`
  round-trip the index through pretty-printed UTF-8 JSON. A custom
  `IndexNotFoundError` (subclass of `FileNotFoundError`) gives a clear
  message when the index file is missing.

* **[src/search.py](src/search.py).** `print_word` formats one term's
  entry for the user. `parse_query` turns a raw query string into a
  list of OR-groups, each with positive terms, phrases, and negatives.
  `find` resolves each group and combines them. `find_with_suggestions`
  adds did-you-mean hints when no document matches.

* **[src/main.py](src/main.py).** REPL dispatcher. Errors from any
  handler are caught and surfaced as friendly messages. `Ctrl-D` and
  `Ctrl-C` exit cleanly. The `build` command streams progress to stdout
  per fetched page so the user can see the crawl is alive during the
  long politeness-bound wait.


## Inverted index design

The index uses a nested dictionary keyed first by token, then by URL:

```python
{
    "love": {
        "https://quotes.toscrape.com/page/3/": {
            "frequency": 2,
            "positions": [12, 47],
        },
        ...
    },
    ...
}
```

Three properties motivated this shape:

1. **O(1) average lookup** of any term's posting list, since both the
   outer and inner containers are dictionaries.
2. **Per-document statistics live together.** Term frequency feeds
   TF-IDF ranking, and the positions list enables true phrase search
   (verified by checking adjacency, not just co-occurrence). Both are
   needed by `find`, so storing them as siblings means there is no
   join at query time.
3. **Maps cleanly onto JSON,** which is what we persist anyway.

Tokenisation rules follow the brief: lowercase everything, strip
punctuation (including a small set of Unicode characters that occur on
the live site but are not in `string.punctuation`), split on
whitespace, and keep stopwords. Keeping stopwords means `print the`
and `find the` remain useful demos.


## Query language

`find` accepts four query forms. The first three can be combined.

### Plain keyword search (default AND)

```
find good friends
```

Returns pages that contain every listed word. The query is tokenised
the same way the index was built, so case, punctuation, and Unicode
quotes do not matter.

### Phrase search

```
find "good friends"
```

A double-quoted segment is a phrase. The engine finds documents that
contain every word in the phrase, then verifies that the words appear
at consecutive token positions using the position lists stored in the
index. A page that contains both words far apart will not match.

### Boolean operators

Uppercase `AND`, `OR`, and `NOT` are recognised as operators. Lowercase
`and` / `or` / `not` are still ordinary search terms, so prose like
`cats and dogs` is not accidentally re-interpreted.

| Query | Behaviour |
| --- | --- |
| `find love AND life` | Same as `find love life`. `AND` is the redundant default and is silently dropped. |
| `find love OR hate` | Union of the two single-term result sets. |
| `find love NOT hate` | Pages that contain `love` but not `hate`. |
| `find love NOT hate OR fish` | Reads as `(love NOT hate) ∪ fish`. |

A pure-`NOT` query (for example `find NOT hate`) returns nothing,
because there is no positive anchor to score documents against.

### Did-you-mean suggestions

If `print` cannot find a word, or if `find` returns no results, the
engine looks for near-spelling matches in the index vocabulary using
`difflib.get_close_matches` with a similarity cutoff of 0.7. Examples:

```
> print lvoe
'lvoe' is not in the index. Did you mean: love, live?
> find lvoe
No results. Did you mean: 'lvoe' → love, live?
```

The cutoff is high enough that totally unrelated typos (for example
`xyzzy`) produce no suggestions rather than noisy ones.


## TF-IDF ranking

The brief specifies the ranking formula. For document `d` and query
term `t`:

* `tf(t, d) = freq(t, d) / total_tokens(d)`. Term frequency is divided
  by the document length, which is itself computed as the sum of all
  term frequencies for that document. Storing per-term frequencies
  makes this an exact computation, not an estimate.
* `idf(t) = log(N / df(t))` where `N` is the number of distinct
  documents and `df(t)` is the number of documents containing `t`.
  Natural log is used.
* For multi-term queries the per-term TF-IDF scores are summed.

Phrase tokens contribute to the score the same way bare keywords do,
so a phrase match also ranks against the corpus.

Ties on score are broken alphabetically by URL. This makes results
deterministic, which matters for testability.


## Complexity

This section gives the asymptotic cost of each operation in the
pipeline. The symbols used throughout are:

* `n`: characters in a single HTML document.
* `P`: number of pages in the corpus.
* `L`: mean number of tokens per page.
* `t`: number of terms in a query.
* `p`: number of documents that contain every positive query term
  (the size of the AND-intersection).
* `m`: mean length of a position list per `(term, document)` pair.
* `V`: number of distinct terms in the index vocabulary.
* `I`: total size of the serialised index in bytes.

### Tokenisation: `O(n)`

`extract_text` walks the HTML once with BeautifulSoup, then applies
two `str.translate` passes and a final whitespace split. Each step is
linear in the input length, so per-page tokenisation is `O(n)`.

### Build: `O(P · L)`

For every page the indexer tokenises the text (`Θ(L)` on average),
walks each token once, and updates the nested dictionary in `O(1)`
average per token. Across the corpus this is `Θ(P · L)` time and the
same in space for the resulting index.

### Save / load: `O(I)`

`save_index` writes the entire dictionary as pretty-printed JSON in
one pass. `load_index` parses it back in one pass. Both are linear in
the on-disk size `I`.

### Single-term lookup: `O(1)` average

`index.get(term)` is an average-case `O(1)` dictionary lookup. The
worst-case dictionary lookup is `O(V)` after hash collisions, which
is stated only for completeness; in practice every term is `O(1)`.

### Multi-term AND query: `O(t · p_min)` to intersect, `O(t · p)` to score

`_intersect_postings` sorts the per-term posting sets by size and
intersects smallest-first, bounding the work by the size of the
smallest list `p_min` times the number of query terms `t`. Once the
candidate set is fixed, `_score` evaluates every term for every
surviving document, giving `O(t · p)` for the scoring pass. Sorting
the final results adds `O(p · log p)`.

### Phrase query: `O(p · k · m)`

After AND-intersection, `_has_phrase_at` checks each candidate URL by
materialising the position sets for every phrase token and walking
the first token's positions. With `k` tokens in the phrase the work
per document is `O(k · m)`. Across all `p` candidates the total is
`O(p · k · m)`, which is dominated by `O(p · m)` for short phrases.

### Suggestion lookup: `O(V · |term|)`

`difflib.get_close_matches` compares the query token against every
indexed term using a Ratcliff/Obershelp similarity computation that
is roughly proportional to the term length. This runs only on a
no-result query, so the cost is paid at most once per failed search.


## Installation

Python 3.9 or newer is required. The codebase uses
`from __future__ import annotations` for forward references in type
hints.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Dependencies

| Package | Why |
| --- | --- |
| `requests` | HTTP client used by the crawler. |
| `beautifulsoup4` | HTML parsing for link extraction and text cleanup. |
| `pytest` | Test runner. |
| `pytest-cov` | Coverage reporting. |


## Usage examples

Start the shell:

```bash
python -m src.main
```

### `build`

```
> build 5
Crawling https://quotes.toscrape.com/ (capped at 5 pages). A 6-second
politeness delay runs between every request, so the full site takes a
few minutes. Progress prints below.
  [1] fetched https://quotes.toscrape.com/
  [2] fetched https://quotes.toscrape.com/author/Albert-Einstein
  [3] fetched https://quotes.toscrape.com/tag/change/
  [4] fetched https://quotes.toscrape.com/tag/deep-thoughts/
  [5] fetched https://quotes.toscrape.com/tag/thinking/
Fetched 5 page(s). Building index...
Index built (464 unique terms) and saved to data/index.json.
```

Run plain `build` (no argument) for the full submission run.

### `load`

```
> load
Loaded index with 464 term(s) from data/index.json.
```

Useful in a fresh session so the crawler does not have to run again.

### `print`

```
> print love
'love' appears in 4 document(s):
  https://quotes.toscrape.com/
    frequency: 2
    positions: [198, 274]
  https://quotes.toscrape.com/tag/change/
    frequency: 1
    positions: [44]
  ...
```

A misspelling is tolerated:

```
> print lvoe
'lvoe' is not in the index. Did you mean: love, live?
```

### `find`

A simple keyword query:

```
> find love
4 result(s) for 'love' (ranked by TF-IDF):
  1. https://quotes.toscrape.com/tag/change/
  2. https://quotes.toscrape.com/tag/deep-thoughts/
  3. https://quotes.toscrape.com/tag/thinking/
  4. https://quotes.toscrape.com/
```

A phrase query (note the `Phrase search:` label):

```
> find "good friends"
Phrase search: "good friends"
0 result(s) (ranked by TF-IDF):
```

A boolean query:

```
> find love OR hate
Boolean query: love OR hate
4 result(s) (ranked by TF-IDF):
  1. https://quotes.toscrape.com/tag/change/
  2. https://quotes.toscrape.com/tag/deep-thoughts/
  3. https://quotes.toscrape.com/tag/thinking/
  4. https://quotes.toscrape.com/
```


## Testing

### Running the tests

```bash
pytest --cov=src tests/ --cov-report=term-missing
```

The full suite runs in well under a second. It uses **only mocked
HTTP**, so no network call is made during testing. This keeps the
tests fast and means the live site is never hit by accident.

### Test layout

| File | Covers |
| --- | --- |
| `tests/test_crawler.py` | Politeness, link filtering, dedup, fragment handling, URL canonicalisation, error handling, parse-error tolerance. |
| `tests/test_indexer.py` | Tokenisation rules (lowercase, punctuation, Unicode, whitespace), `extract_text` HTML cleanup, position tracking, multi-page aggregation. |
| `tests/test_storage.py` | JSON round-trip, missing-file handling, Unicode safety, parent-directory creation, invalid-JSON behaviour. |
| `tests/test_search.py` | `print_word`, AND queries, phrase queries, boolean operators, did-you-mean, TF-IDF ranking, case insensitivity, deterministic tie-breaking. |
| `tests/test_main.py` | REPL dispatch, command handlers, `Ctrl-D` and `Ctrl-C` handling, exit semantics. |
| `tests/test_integration.py` | Full pipeline crawl, index, save, load, find. |

### Testing strategy

The project follows three principles.

**Mock the network at the lowest level.** Tests patch
`src.crawler.requests.get` and `src.crawler.time.sleep`. The crawler
sees fake responses and never sleeps, so a politeness assertion can
check that `time.sleep` was called the correct number of times rather
than waiting for it. This means the suite runs in milliseconds and is
safe to run in CI.

**Test pure helpers directly.** `tokenize`, `extract_text`,
`_canonicalise`, `_has_phrase_at`, `parse_query`, and `suggest_terms`
are all reachable as pure functions, so each one is exercised on its
own without setting up a `Crawler` or a `Shell`.

**Cover dispatch and integration as well as units.** `test_main.py`
exercises the REPL at the dispatcher layer (calling `dispatch`
directly) and `test_integration.py` runs the full pipeline end-to-end
against an in-memory fake site so any wiring mistake between modules
is caught.

### Coverage

The current line coverage is around 94% across the `src` package.
Uncovered lines are mostly defensive branches (rare
`requests.RequestException` paths, EOF handling in the REPL) which
have no test data without mocking lower-level system behaviour.


## Example terminal outputs

A short end-to-end session covering every command:

```
$ python -m src.main
Quotes search engine. Type 'help' for commands, 'exit' to quit.
> help
Available commands:
  build [max_pages]  crawl the site and build a fresh index
                     (optional cap: 'build 10' fetches at most 10 pages)
  load               load the saved index from data/index.json
  print <word>       show the index entry for one word
  find <query>       search (multi-word = AND, ranked by TF-IDF)
  help               show this message
  exit | quit        leave the shell
> build 5
Crawling https://quotes.toscrape.com/ (capped at 5 pages). A 6-second
politeness delay runs between every request, so the full site takes a
few minutes. Progress prints below.
  [1] fetched https://quotes.toscrape.com/
  [2] fetched https://quotes.toscrape.com/author/Albert-Einstein
  [3] fetched https://quotes.toscrape.com/tag/change/
  [4] fetched https://quotes.toscrape.com/tag/deep-thoughts/
  [5] fetched https://quotes.toscrape.com/tag/thinking/
Fetched 5 page(s). Building index...
Index built (464 unique terms) and saved to data/index.json.
> find love
4 result(s) for 'love' (ranked by TF-IDF):
  1. https://quotes.toscrape.com/tag/change/
  2. https://quotes.toscrape.com/tag/deep-thoughts/
  3. https://quotes.toscrape.com/tag/thinking/
  4. https://quotes.toscrape.com/
> find love AND life
Boolean query: love AND life
4 result(s) (ranked by TF-IDF):
  1. https://quotes.toscrape.com/tag/change/
  2. https://quotes.toscrape.com/tag/deep-thoughts/
  3. https://quotes.toscrape.com/tag/thinking/
  4. https://quotes.toscrape.com/
> find love NOT hate
Boolean query: love NOT hate
4 result(s) (ranked by TF-IDF):
  1. https://quotes.toscrape.com/tag/change/
  ...
> print love
'love' appears in 4 document(s):
  https://quotes.toscrape.com/
    frequency: 2
    positions: [198, 274]
  ...
> print lvoe
'lvoe' is not in the index. Did you mean: love, live?
> exit
```


## Known limitations

A few rough edges are documented honestly rather than papered over.

* **Un-smoothed IDF.** A term that appears in every document scores
  zero under `log(N/df)` and ranking can no longer differentiate among
  those documents. A smoothed variant such as `log((N+1)/(df+1)) + 1`
  would avoid this. The brief specified the un-smoothed formula, so it
  is the formula the project implements.

* **NOT only excludes single tokens.** `NOT word` excludes any
  document containing `word`. `NOT "phrase"` is parsed as excluding
  any document containing any of the phrase's tokens, rather than
  excluding only documents where the phrase appears as an adjacent
  sequence. A precise negative phrase would require running the
  positional adjacency check in reverse.

* **`document_length` approximation.** The denominator of the term
  frequency calculation is the sum of all per-term frequencies for a
  document. For the data we collect, every token in the document
  contributes one to exactly one posting, so this sum is exact. If
  fields with different weights were ever introduced (for example a
  separate title field) the calculation would need to change.

* **Crawl scope is fixed.** The crawler will only follow links inside
  `quotes.toscrape.com`. The allowed domain lives in
  [src/config.py](src/config.py); changing target sites requires
  editing that constant rather than passing a flag.

* **Single-process crawler.** The politeness window of six seconds is
  enforced by `time.sleep`. A multi-worker crawler would need a more
  sophisticated rate limiter to maintain the same per-host cadence.


## GenAI declaration and reflection

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
│   ├── test_main.py
│   ├── test_search.py
│   └── test_storage.py
├── data/
│   └── (index.json produced by `build`, gitignored)
├── requirements.txt
├── README.md
└── .gitignore
```
