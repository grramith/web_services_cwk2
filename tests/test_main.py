"""Unit tests for the interactive :mod:`src.main` shell.

The REPL is exercised at the dispatch layer rather than by feeding stdin to
:meth:`Shell.run`. Each command handler is a pure method, so calling it
directly gives us deterministic coverage without poking at ``input()``.

The one test that does drive :meth:`Shell.run` (`test_run_eof_exits_cleanly`)
uses :func:`unittest.mock.patch` to stub ``input``.
"""

from __future__ import annotations

import io
from typing import Dict
from unittest.mock import patch

import pytest

from src.indexer import Indexer, InvertedIndex
from src.main import Shell, main


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def loaded_shell(tmp_path) -> Shell:
    """A :class:`Shell` whose ``index`` attribute is a small, real index."""
    pages: Dict[str, str] = {
        "http://a/": "<p>hello world</p>",
        "http://b/": "<p>hello again world</p>",
    }
    shell = Shell(index_path=str(tmp_path / "index.json"))
    shell.index = Indexer().build_index(pages)
    return shell


@pytest.fixture
def empty_shell(tmp_path) -> Shell:
    """A :class:`Shell` with no index loaded."""
    return Shell(index_path=str(tmp_path / "index.json"))


# --------------------------------------------------------------------------- #
# dispatch                                                                    #
# --------------------------------------------------------------------------- #


def test_dispatch_exit_returns_false(empty_shell: Shell) -> None:
    """``exit`` and ``quit`` both stop the loop."""
    assert empty_shell.dispatch("exit") is False
    assert empty_shell.dispatch("quit") is False
    assert empty_shell.dispatch("EXIT") is False  # case-insensitive


def test_dispatch_unknown_command_keeps_loop_alive(
    empty_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unrecognised command must print a hint, not crash."""
    assert empty_shell.dispatch("frobnicate") is True
    out = capsys.readouterr().out
    assert "Unknown command" in out
    assert "help" in out


def test_dispatch_handler_exception_is_caught(
    empty_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    """If a handler raises, the shell prints the error and survives."""

    def boom(_args):
        raise RuntimeError("kaboom")

    empty_shell._handlers["explode"] = boom  # type: ignore[assignment]
    assert empty_shell.dispatch("explode now") is True
    out = capsys.readouterr().out
    assert "Error: kaboom" in out


# --------------------------------------------------------------------------- #
# help                                                                        #
# --------------------------------------------------------------------------- #


def test_help_lists_every_command(
    empty_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    empty_shell.dispatch("help")
    out = capsys.readouterr().out
    for cmd in ("build", "load", "print", "find", "exit"):
        assert cmd in out


# --------------------------------------------------------------------------- #
# print                                                                       #
# --------------------------------------------------------------------------- #


def test_print_without_arg_shows_usage(
    loaded_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    loaded_shell.dispatch("print")
    out = capsys.readouterr().out
    assert "Usage: print <word>" in out


def test_print_without_index_shows_friendly_error(
    empty_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    empty_shell.dispatch("print hello")
    out = capsys.readouterr().out
    assert "No index loaded" in out


def test_print_existing_word_shows_posting(
    loaded_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    loaded_shell.dispatch("print hello")
    out = capsys.readouterr().out
    assert "hello" in out
    assert "http://a/" in out
    assert "frequency" in out


def test_print_uses_only_first_token(
    loaded_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    """``print foo bar`` should look up ``foo`` and ignore the rest."""
    loaded_shell.dispatch("print hello world")
    out = capsys.readouterr().out
    assert "hello" in out
    # ``world`` shouldn't be reported as a separate posting header.
    assert "'world' is not in the index" not in out


# --------------------------------------------------------------------------- #
# find                                                                        #
# --------------------------------------------------------------------------- #


def test_find_without_arg_shows_usage(
    loaded_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    loaded_shell.dispatch("find")
    out = capsys.readouterr().out
    assert "Usage: find <query>" in out


def test_find_without_index_shows_friendly_error(
    empty_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    empty_shell.dispatch("find hello")
    out = capsys.readouterr().out
    assert "No index loaded" in out


def test_find_no_results_prints_no_results(
    loaded_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    loaded_shell.dispatch("find nonexistent")
    out = capsys.readouterr().out
    assert "No results" in out


def test_find_returns_ranked_results(
    loaded_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    loaded_shell.dispatch("find hello")
    out = capsys.readouterr().out
    assert "result(s) for 'hello'" in out
    assert "TF-IDF" in out
    assert "http://a/" in out
    assert "http://b/" in out


# --------------------------------------------------------------------------- #
# load                                                                        #
# --------------------------------------------------------------------------- #


def test_load_missing_file_prints_friendly_error(
    empty_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    empty_shell.dispatch("load")
    out = capsys.readouterr().out
    assert "No index file" in out


def test_load_after_save_round_trips(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Build an index, save it via storage, then ``load`` from the shell."""
    from src.storage import save_index

    pages = {"http://a/": "<p>hi there</p>"}
    index = Indexer().build_index(pages)
    path = str(tmp_path / "index.json")
    save_index(index, path)

    shell = Shell(index_path=path)
    shell.dispatch("load")
    out = capsys.readouterr().out

    assert "Loaded index" in out
    assert shell.index is not None
    assert "hi" in shell.index


def test_load_invalid_json_prints_parse_error(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "index.json"
    path.write_text("{not valid json", encoding="utf-8")
    shell = Shell(index_path=str(path))
    shell.dispatch("load")
    out = capsys.readouterr().out
    assert "Could not parse index file" in out


# --------------------------------------------------------------------------- #
# build                                                                       #
# --------------------------------------------------------------------------- #


def test_build_invokes_crawler_and_persists(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``build`` should drive crawler -> indexer -> storage end-to-end."""
    path = str(tmp_path / "index.json")
    shell = Shell(index_path=path)

    fake_pages = {"http://quotes.toscrape.com/": "<p>be the change</p>"}

    with patch("src.main.Crawler") as crawler_cls:
        crawler_cls.return_value.crawl.return_value = fake_pages
        shell.dispatch("build")

    out = capsys.readouterr().out
    assert "Crawling" in out
    assert "Index built" in out
    assert shell.index is not None
    assert "change" in shell.index
    # storage actually wrote something
    import os
    assert os.path.exists(path)


def test_build_handles_crawl_error(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    from src.crawler import CrawlError

    shell = Shell(index_path=str(tmp_path / "index.json"))
    with patch("src.main.Crawler") as crawler_cls:
        crawler_cls.return_value.crawl.side_effect = CrawlError("nope")
        shell.dispatch("build")

    out = capsys.readouterr().out
    assert "Crawl aborted" in out
    assert shell.index is None


# --------------------------------------------------------------------------- #
# run() loop                                                                  #
# --------------------------------------------------------------------------- #


def test_run_eof_exits_cleanly(
    empty_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pressing Ctrl-D at the prompt should exit with code 0."""
    with patch("builtins.input", side_effect=EOFError):
        rc = empty_shell.run()
    assert rc == 0


def test_run_keyboard_interrupt_exits_cleanly(
    empty_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch("builtins.input", side_effect=KeyboardInterrupt):
        rc = empty_shell.run()
    assert rc == 0
    assert "Interrupted" in capsys.readouterr().out


def test_run_processes_commands_then_exits(
    empty_shell: Shell, capsys: pytest.CaptureFixture[str]
) -> None:
    """Feed a sequence of inputs and confirm the loop dispatches them."""
    inputs = iter(["", "help", "exit"])
    with patch("builtins.input", lambda _prompt: next(inputs)):
        rc = empty_shell.run()
    assert rc == 0
    out = capsys.readouterr().out
    assert "Available commands" in out


def test_main_entry_point_runs_shell() -> None:
    """The module-level :func:`main` should construct a Shell and run it."""
    with patch("src.main.Shell") as shell_cls:
        shell_cls.return_value.run.return_value = 0
        rc = main([])
    assert rc == 0
    shell_cls.assert_called_once()
    shell_cls.return_value.run.assert_called_once()
