"""Interactive shell entry point for the quotes search engine.

Run as a module so relative imports resolve correctly::

    python -m src.main

The shell exposes five commands at a ``>`` prompt:

* ``build``        — crawl the live site, build the index, save it to disk.
* ``load``         — load an index that was saved earlier.
* ``print <word>`` — pretty-print one term's posting list.
* ``find <query>`` — return URLs ranked by TF-IDF (multi-word = AND).
* ``exit`` / ``quit`` — leave the shell. ``Ctrl-D`` and ``Ctrl-C`` work too.
"""

from __future__ import annotations

import logging
import sys
from typing import Callable, Dict, List, Optional

from src.config import BASE_URL, DEFAULT_INDEX_PATH
from src.crawler import CrawlError, Crawler
from src.indexer import Indexer, InvertedIndex
from src.search import (
    extract_snippet,
    find_with_suggestions,
    print_word,
    query_positive_terms,
    score_results,
)
from src.storage import (
    IndexNotFoundError,
    load_index,
    load_index_metadata,
    save_index,
)


PROMPT = "> "
HELP_TEXT = (
    "Available commands:\n"
    "  build [max_pages] [--stem]  crawl the site and build a fresh index\n"
    "                              (optional cap: 'build 10' fetches at most 10 pages;\n"
    "                               --stem enables Porter stemming, default OFF)\n"
    "  load                        load the saved index from data/index.json\n"
    "  print <word>                show the index entry for one word\n"
    "  find <query>                search (multi-word = AND, ranked by TF-IDF)\n"
    "  help                        show this message\n"
    "  exit | quit                 leave the shell"
)


class Shell:
    """REPL state holder.

    Keeping the state on an instance (rather than in module-level globals)
    means tests can drive the shell command-by-command without subprocess
    juggling.
    """

    def __init__(self, index_path: str = DEFAULT_INDEX_PATH) -> None:
        """Construct an empty REPL.

        Args:
            index_path: Filesystem location used by ``build`` /
                ``load`` for persistent storage. Tests override this
                to point at a temporary path.

        Initial state is "no index loaded, stemming off"; ``build`` or
        ``load`` populate :attr:`index`, and ``load`` may flip
        :attr:`stem` on if the on-disk metadata says the index was
        built with the Porter stemmer.
        """
        self.index_path = index_path
        self.index: Optional[InvertedIndex] = None
        self.stem: bool = False
        self._handlers: Dict[str, Callable[[List[str]], None]] = {
            "build": self.cmd_build,
            "load": self.cmd_load,
            "print": self.cmd_print,
            "find": self.cmd_find,
            "help": self.cmd_help,
        }

    # ------------------------------------------------------------------ #
    # Loop                                                                #
    # ------------------------------------------------------------------ #

    def run(self) -> int:
        """Run the interactive loop. Returns the desired process exit code."""
        print(
            "Quotes search engine. Type 'help' for commands, "
            "'exit' to quit."
        )
        while True:
            try:
                raw = input(PROMPT)
            except EOFError:
                print()
                return 0
            except KeyboardInterrupt:
                print("\nInterrupted.")
                return 0

            if not raw.strip():
                continue
            if not self.dispatch(raw):
                return 0
        # unreachable
        return 0

    def dispatch(self, raw: str) -> bool:
        """Process one input line. Return ``False`` if the loop should stop."""
        parts = raw.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        args_str = parts[1] if len(parts) > 1 else ""

        if cmd in {"exit", "quit"}:
            return False

        handler = self._handlers.get(cmd)
        if handler is None:
            print(f"Unknown command: {cmd!r}. Type 'help' for the list.")
            return True

        # ``find`` and ``print`` care about the raw string; the simple
        # commands ignore arguments. Splitting once gives us both forms.
        try:
            handler([args_str] if args_str else [])
        except Exception as exc:  # noqa: BLE001 — surface any handler bug
            print(f"Error: {exc}")
        return True

    # ------------------------------------------------------------------ #
    # Command handlers                                                    #
    # ------------------------------------------------------------------ #

    def cmd_help(self, _args: List[str]) -> None:
        """Print the built-in command reference.

        Args:
            _args: Ignored — ``help`` accepts no arguments. The leading
                underscore signals that the parameter exists only to
                satisfy the dispatcher's uniform handler signature.
        """
        print(HELP_TEXT)

    def cmd_build(self, args: List[str]) -> None:
        """Crawl, index, and save. Optional first arg caps the page count.

        Accepts an optional ``--stem`` flag (anywhere in the argument
        list) that enables the Porter stemmer for the build. The flag
        is persisted in the index metadata so subsequent ``load`` calls
        can configure search consistently.
        """
        tokens = args[0].split() if args and args[0].strip() else []
        stem = False
        positional: List[str] = []
        for token in tokens:
            if token == "--stem":
                stem = True
            else:
                positional.append(token)

        max_pages: Optional[int] = None
        if positional:
            head = positional[0]
            try:
                max_pages = int(head)
                if max_pages <= 0:
                    raise ValueError
            except ValueError:
                print(f"Usage: build [max_pages] [--stem]  (got {head!r})")
                return

        cap_note = f" (capped at {max_pages} pages)" if max_pages else ""
        stem_note = ", Porter stemmer ON" if stem else ""
        print(
            f"Crawling {BASE_URL}{cap_note}{stem_note}. "
            f"A 6-second politeness delay runs between every request, "
            f"so the full site takes a few minutes — progress prints below."
        )
        try:
            pages = Crawler(max_pages=max_pages).crawl(
                BASE_URL,
                on_page=lambda url, n: print(f"  [{n}] fetched {url}", flush=True),
            )
        except CrawlError as exc:
            print(f"Crawl aborted: {exc}")
            return
        print(f"Fetched {len(pages)} page(s). Building index...")
        self.index = Indexer(stem=stem).build_index(pages)
        save_index(self.index, self.index_path, stem=stem)
        self.stem = stem
        print(
            f"Index built ({len(self.index)} unique terms) "
            f"and saved to {self.index_path}."
        )

    def cmd_load(self, _args: List[str]) -> None:
        """Replace the in-memory index with the one stored on disk.

        Reads :attr:`index_path` and the matching ``.meta.json``
        sidecar. Surface-level error messages are printed for the two
        recoverable failure modes (missing file, malformed JSON) so
        the REPL keeps running.

        Args:
            _args: Ignored — ``load`` accepts no arguments.
        """
        try:
            self.index = load_index(self.index_path)
        except IndexNotFoundError as exc:
            print(str(exc))
            return
        except ValueError as exc:
            print(f"Could not parse index file: {exc}")
            return
        meta = load_index_metadata(self.index_path)
        self.stem = bool(meta.get("stem", False))
        stem_note = " (Porter stemmer ON)" if self.stem else ""
        print(
            f"Loaded index with {len(self.index)} term(s) from "
            f"{self.index_path}{stem_note}."
        )

    def cmd_print(self, args: List[str]) -> None:
        """Display the inverted-index entry for one term.

        Args:
            args: Single-element list whose value is the rest of the
                user's input line. Only the first whitespace-delimited
                token of that string is treated as the lookup key —
                anything after it is ignored, in line with the brief.

        Prints a short usage hint when ``args`` is empty and a
        "no index loaded" reminder when neither ``build`` nor
        ``load`` has been run yet.
        """
        if not args or not args[0].strip():
            print("Usage: print <word>")
            return
        if self.index is None:
            print("No index loaded — run 'build' or 'load' first.")
            return
        word = args[0].split()[0]  # only the first token is meaningful
        print_word(self.index, word)

    def cmd_find(self, args: List[str]) -> None:
        """Run a query against the loaded index and print the ranked URLs.

        Recognises the full query language exposed by
        :func:`src.search.find_with_suggestions` — bare words AND'd by
        default, ``"..."`` for phrase search, uppercase
        ``AND``/``OR``/``NOT`` operators, and edit-distance "did you
        mean" hints when retrieval comes back empty. Each result line
        is followed by a one-line snippet that highlights matched
        terms in ANSI bold (TTY) or ``**markdown**`` (otherwise).

        Args:
            args: Single-element list whose value is the rest of the
                user's input line. The full string is forwarded to the
                search helpers verbatim so phrase-quoting rules behave
                exactly as a user typing the same query at the prompt.

        Prints a short usage hint when ``args`` is empty and a
        "no index loaded" reminder when no index has been built or
        loaded.
        """
        if not args or not args[0].strip():
            print("Usage: find <query>")
            return
        if self.index is None:
            print("No index loaded — run 'build' or 'load' first.")
            return
        query = args[0]
        results, suggestions = find_with_suggestions(
            self.index, query, stem=self.stem
        )
        if not results:
            if suggestions:
                hints = "; ".join(
                    f"'{term}' → {', '.join(candidates)}"
                    for term, candidates in suggestions
                )
                print(f"No results. Did you mean: {hints}?")
            else:
                print("No results.")
            return
        print(f"Search results for: {query}")
        print("Ranking method: TF-IDF")
        print(f"Results found: {len(results)}")
        print()
        snippet_terms = query_positive_terms(query, stem=self.stem)
        ansi = sys.stdout.isatty()
        scored = score_results(self.index, query, results, stem=self.stem)
        for rank, (url, (score, freqs)) in enumerate(
            zip(results, scored), start=1
        ):
            print(f"[{rank}] {url}")
            print(f"    TF-IDF score : {score:.5f}")
            if len(freqs) <= 1:
                only_term = next(iter(freqs.keys()), None)
                only_count = next(iter(freqs.values()), 0)
                print(f"    Term frequency : {only_count} occurrence(s)")
                if only_term is not None:
                    print(f"    Matched term(s) : {only_term}")
            else:
                total = sum(freqs.values())
                print(f"    Total frequency : {total} occurrence(s)")
                print(f"    Matched terms : {', '.join(freqs.keys())}")
                print("    Term breakdown:")
                for term, count in freqs.items():
                    print(f"      - {term}: {count} occurrence(s)")
            snippet = extract_snippet(
                self.index, url, snippet_terms, ansi=ansi
            )
            if snippet:
                print("    Snippet:")
                print(f'    "{snippet}"')
            print()


def main(argv: Optional[List[str]] = None) -> int:
    """Module entry point. ``argv`` is accepted for symmetry with tests."""
    del argv  # CLI takes no arguments at the moment
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return Shell().run()


if __name__ == "__main__":
    sys.exit(main())
