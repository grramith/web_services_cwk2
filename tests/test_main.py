"""Unit tests for the interactive :mod:`src.main` shell — dispatch layer.

The REPL is exercised at the dispatch layer rather than by feeding stdin to
:meth:`Shell.run`. Each command handler is a pure method, so calling it
directly gives us deterministic coverage without poking at ``input()``.
"""

from __future__ import annotations

from typing import Dict

import pytest

from src.indexer import Indexer
from src.main import Shell


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
