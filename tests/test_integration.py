"""End-to-end integration tests.

These tests wire the crawler, indexer, storage, and search modules together
the same way the live CLI does — but the crawler's HTTP layer is mocked so
they never hit the real website. The fixture HTML is small but exercises
the full pipeline: link following, indexing, persistence, and TF-IDF search.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest

from src.crawler import Crawler
from src.indexer import Indexer
from src.main import Shell
from src.search import find
from src.storage import load_index, save_index


# --------------------------------------------------------------------------- #
# Fixture HTML                                                                #
# --------------------------------------------------------------------------- #


FIXTURE_PAGES: Dict[str, str] = {
    "https://quotes.toscrape.com/": """
        <html><body>
          <div class="quote">
            <span class="text">The world as we have created it</span>
            <span class="author">Albert Einstein</span>
          </div>
          <a href="/page/2/">Next</a>
          <a href="https://example.com/external">External</a>
        </body></html>
    """,
    "https://quotes.toscrape.com/page/2/": """
        <html><body>
          <div class="quote">
            <span class="text">It is our choices that show what we truly are</span>
            <span class="author">J. K. Rowling</span>
          </div>
          <a href="/page/1/">Back</a>
        </body></html>
    """,
    "https://quotes.toscrape.com/page/1/": """
        <html><body>
          <div class="quote">
            <span class="text">There is no friend as loyal as a book</span>
            <span class="author">Ernest Hemingway</span>
          </div>
        </body></html>
    """,
}


def _make_response(status: int = 200, text: str = "") -> MagicMock:
    """Tiny ``requests.Response`` lookalike."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


# --------------------------------------------------------------------------- #
# Pipeline test                                                               #
# --------------------------------------------------------------------------- #


def test_crawl_index_save_load_find(tmp_path: Path) -> None:
    """Crawl (mocked) → index → save → reload → search must work end-to-end."""

    def fake_get(url: str, **_: object) -> MagicMock:
        return _make_response(200, FIXTURE_PAGES[url])

    with patch("src.crawler.requests.get", side_effect=fake_get), \
         patch("src.crawler.time.sleep"):
        pages = Crawler().crawl("https://quotes.toscrape.com/")

    assert len(pages) == 3

    index = Indexer().build_index(pages)
    assert "world" in index
    assert "book" in index

    index_path = tmp_path / "index.json"
    save_index(index, str(index_path))
    reloaded = load_index(str(index_path))
    assert reloaded == index

    # Single-term query.
    assert find(reloaded, "Einstein") == ["https://quotes.toscrape.com/"]
    # AND-query: only page 1 has both ``friend`` and ``book``.
    assert find(reloaded, "friend book") == [
        "https://quotes.toscrape.com/page/1/"
    ]
    # Multi-term query that no document satisfies.
    assert find(reloaded, "einstein book") == []


# --------------------------------------------------------------------------- #
# Shell-level test                                                            #
# --------------------------------------------------------------------------- #


def test_shell_build_then_find(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The shell's ``build`` and ``find`` commands must compose cleanly."""

    def fake_get(url: str, **_: object) -> MagicMock:
        return _make_response(200, FIXTURE_PAGES[url])

    shell = Shell(index_path=str(tmp_path / "index.json"))

    with patch("src.crawler.requests.get", side_effect=fake_get), \
         patch("src.crawler.time.sleep"):
        shell.dispatch("build")
        shell.dispatch("find Einstein")

    out = capsys.readouterr().out
    assert "https://quotes.toscrape.com/" in out
    assert "Index built" in out


def test_shell_load_without_file_reports_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``load`` against a missing file must give a friendly message, not crash."""
    shell = Shell(index_path=str(tmp_path / "missing.json"))
    shell.dispatch("load")

    out = capsys.readouterr().out
    assert "No index file" in out


def test_shell_print_or_find_without_index_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``print`` / ``find`` before any index is loaded must explain the situation."""
    shell = Shell(index_path=str(tmp_path / "index.json"))
    shell.dispatch("print hello")
    shell.dispatch("find world")

    out = capsys.readouterr().out
    assert out.count("No index loaded") == 2


def test_shell_unknown_command_does_not_crash(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shell = Shell()
    shell.dispatch("frobnicate")

    out = capsys.readouterr().out
    assert "Unknown command" in out


def test_shell_exit_command_stops_loop() -> None:
    """``dispatch`` must return ``False`` for exit/quit so the loop breaks."""
    shell = Shell()
    assert shell.dispatch("exit") is False
    assert shell.dispatch("quit") is False
    assert shell.dispatch("help") is True
