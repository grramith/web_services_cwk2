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
from src.search import find, print_word
from src.storage import IndexNotFoundError, load_index, save_index


PROMPT = "> "
HELP_TEXT = (
    "Available commands:\n"
    "  build [max_pages]  crawl the site and build a fresh index\n"
    "                     (optional cap: 'build 10' fetches at most 10 pages)\n"
    "  load               load the saved index from data/index.json\n"
    "  print <word>       show the index entry for one word\n"
    "  find <query>       search (multi-word = AND, ranked by TF-IDF)\n"
    "  help               show this message\n"
    "  exit | quit        leave the shell"
)


class Shell:
    """REPL state holder.

    Keeping the state on an instance (rather than in module-level globals)
    means tests can drive the shell command-by-command without subprocess
    juggling.
    """

    def __init__(self, index_path: str = DEFAULT_INDEX_PATH) -> None:
        self.index_path = index_path
        self.index: Optional[InvertedIndex] = None
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
        print(HELP_TEXT)

    def cmd_build(self, args: List[str]) -> None:
        """Crawl, index, and save. Optional first arg caps the page count."""
        max_pages: Optional[int] = None
        if args and args[0].strip():
            token = args[0].split()[0]
            try:
                max_pages = int(token)
                if max_pages <= 0:
                    raise ValueError
            except ValueError:
                print(f"Usage: build [max_pages]  (got {token!r})")
                return

        cap_note = f" (capped at {max_pages} pages)" if max_pages else ""
        print(
            f"Crawling {BASE_URL}{cap_note}. "
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
        self.index = Indexer().build_index(pages)
        save_index(self.index, self.index_path)
        print(
            f"Index built ({len(self.index)} unique terms) "
            f"and saved to {self.index_path}."
        )

    def cmd_load(self, _args: List[str]) -> None:
        try:
            self.index = load_index(self.index_path)
        except IndexNotFoundError as exc:
            print(str(exc))
            return
        except ValueError as exc:
            print(f"Could not parse index file: {exc}")
            return
        print(
            f"Loaded index with {len(self.index)} term(s) from {self.index_path}."
        )

    def cmd_print(self, args: List[str]) -> None:
        if not args or not args[0].strip():
            print("Usage: print <word>")
            return
        if self.index is None:
            print("No index loaded — run 'build' or 'load' first.")
            return
        word = args[0].split()[0]  # only the first token is meaningful
        print_word(self.index, word)

    def cmd_find(self, args: List[str]) -> None:
        if not args or not args[0].strip():
            print("Usage: find <query>")
            return
        if self.index is None:
            print("No index loaded — run 'build' or 'load' first.")
            return
        query = args[0]
        results = find(self.index, query)
        if not results:
            print("No results.")
            return
        print(f"{len(results)} result(s) for {query!r} (ranked by TF-IDF):")
        for rank, url in enumerate(results, start=1):
            print(f"  {rank}. {url}")


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
