"""Unit tests for :mod:`src.crawler`.

All HTTP traffic is mocked — these tests must never touch the live website.
``time.sleep`` is also patched so tests stay fast and so we can assert on the
politeness behaviour directly.
"""

from __future__ import annotations

from typing import Dict
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.crawler import Crawler, CrawlError


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _make_response(status: int = 200, text: str = "") -> MagicMock:
    """Build a minimal mock that quacks like a ``requests.Response``."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


def _fake_site() -> Dict[str, str]:
    """A tiny fake ``quotes.toscrape.com`` with a few internal links."""
    return {
        "https://quotes.toscrape.com/": (
            "<html><body>"
            "<a href='/page/2/'>Next</a>"
            "<a href='https://example.com/external'>External</a>"
            "<a href='mailto:a@b.com'>Mail</a>"
            "<p>hello world</p>"
            "</body></html>"
        ),
        "https://quotes.toscrape.com/page/2/": (
            "<html><body>"
            "<a href='/page/1/'>Back</a>"
            "<p>more text</p>"
            "</body></html>"
        ),
        "https://quotes.toscrape.com/page/1/": (
            "<html><body><p>page one</p></body></html>"
        ),
    }


# --------------------------------------------------------------------------- #
# Construction                                                                #
# --------------------------------------------------------------------------- #


def test_crawler_rejects_delay_below_minimum() -> None:
    """The default delay must satisfy the brief's six-second floor."""
    with pytest.raises(CrawlError):
        Crawler(delay=1.0)


def test_crawler_default_user_agent_identifies_us() -> None:
    """The default ``User-Agent`` should clearly identify the crawler."""
    c = Crawler()
    assert "QuotesSearchEngine" in c.user_agent


# --------------------------------------------------------------------------- #
# Politeness                                                                  #
# --------------------------------------------------------------------------- #


def test_crawl_respects_politeness_delay_between_requests() -> None:
    """``time.sleep`` must be called once between successive fetches.

    For three pages we expect exactly two sleeps (none before page 1).
    """
    site = _fake_site()

    def fake_get(url: str, **_: object) -> MagicMock:
        return _make_response(200, site[url])

    with patch("src.crawler.requests.get", side_effect=fake_get) as mocked_get, \
         patch("src.crawler.time.sleep") as mocked_sleep:
        Crawler().crawl("https://quotes.toscrape.com/")

    assert mocked_get.call_count == 3
    assert mocked_sleep.call_count == 2
    for call in mocked_sleep.call_args_list:
        # Each sleep call must be at least the politeness window long.
        (delay_arg,), _ = call
        assert delay_arg >= 6.0


def test_single_page_crawl_issues_no_leading_sleep() -> None:
    """A crawl that returns one page should not sleep before the only fetch."""

    def fake_get(url: str, **_: object) -> MagicMock:
        return _make_response(200, "<html><body>hi</body></html>")

    with patch("src.crawler.requests.get", side_effect=fake_get), \
         patch("src.crawler.time.sleep") as mocked_sleep:
        result = Crawler().crawl("https://quotes.toscrape.com/")

    assert len(result) == 1
    mocked_sleep.assert_not_called()


# --------------------------------------------------------------------------- #
# Link handling                                                               #
# --------------------------------------------------------------------------- #


def test_crawl_skips_external_links() -> None:
    """Links to other domains must never be followed."""
    site = _fake_site()
    seen_urls: list[str] = []

    def fake_get(url: str, **_: object) -> MagicMock:
        seen_urls.append(url)
        return _make_response(200, site.get(url, ""))

    with patch("src.crawler.requests.get", side_effect=fake_get), \
         patch("src.crawler.time.sleep"):
        Crawler().crawl("https://quotes.toscrape.com/")

    assert all("example.com" not in u for u in seen_urls)


def test_crawl_deduplicates_visited_urls() -> None:
    """Following a back-link must not refetch a page already visited."""
    site = _fake_site()
    call_counts: Dict[str, int] = {}

    def fake_get(url: str, **_: object) -> MagicMock:
        call_counts[url] = call_counts.get(url, 0) + 1
        return _make_response(200, site[url])

    with patch("src.crawler.requests.get", side_effect=fake_get), \
         patch("src.crawler.time.sleep"):
        Crawler().crawl("https://quotes.toscrape.com/")

    for url, count in call_counts.items():
        assert count == 1, f"{url} fetched {count} times"


def test_crawl_drops_fragment_identifiers() -> None:
    """``/page/1/#quote-3`` and ``/page/1/`` are the same document."""
    pages = {
        "https://quotes.toscrape.com/": (
            "<html><body>"
            "<a href='/page/1/#a'>A</a>"
            "<a href='/page/1/#b'>B</a>"
            "</body></html>"
        ),
        "https://quotes.toscrape.com/page/1/": "<html>one</html>",
    }
    counts: Dict[str, int] = {}

    def fake_get(url: str, **_: object) -> MagicMock:
        counts[url] = counts.get(url, 0) + 1
        return _make_response(200, pages[url])

    with patch("src.crawler.requests.get", side_effect=fake_get), \
         patch("src.crawler.time.sleep"):
        Crawler().crawl("https://quotes.toscrape.com/")

    assert counts["https://quotes.toscrape.com/page/1/"] == 1


# --------------------------------------------------------------------------- #
# Error handling                                                              #
# --------------------------------------------------------------------------- #


def test_crawl_handles_404_and_continues() -> None:
    """A 404 page must be omitted from the results without aborting."""
    pages = {
        "https://quotes.toscrape.com/": (
            "<html><body>"
            "<a href='/missing/'>Missing</a>"
            "<a href='/ok/'>OK</a>"
            "</body></html>"
        ),
        "https://quotes.toscrape.com/ok/": "<html>ok</html>",
    }

    def fake_get(url: str, **_: object) -> MagicMock:
        if url.endswith("/missing/"):
            return _make_response(404, "not found")
        return _make_response(200, pages[url])

    with patch("src.crawler.requests.get", side_effect=fake_get), \
         patch("src.crawler.time.sleep"):
        result = Crawler().crawl("https://quotes.toscrape.com/")

    assert "https://quotes.toscrape.com/missing/" not in result
    assert "https://quotes.toscrape.com/ok/" in result


def test_crawl_handles_connection_error_and_continues() -> None:
    """Connection errors must be logged and skipped, not propagated."""
    pages = {
        "https://quotes.toscrape.com/": (
            "<html><body>"
            "<a href='/dead/'>Dead</a>"
            "<a href='/alive/'>Alive</a>"
            "</body></html>"
        ),
        "https://quotes.toscrape.com/alive/": "<html>alive</html>",
    }

    def fake_get(url: str, **_: object) -> MagicMock:
        if url.endswith("/dead/"):
            raise requests.exceptions.ConnectionError("boom")
        return _make_response(200, pages[url])

    with patch("src.crawler.requests.get", side_effect=fake_get), \
         patch("src.crawler.time.sleep"):
        result = Crawler().crawl("https://quotes.toscrape.com/")

    assert "https://quotes.toscrape.com/dead/" not in result
    assert "https://quotes.toscrape.com/alive/" in result


def test_crawl_handles_timeout_and_continues() -> None:
    """Timeouts on one page must not stop the crawl."""

    def fake_get(url: str, **_: object) -> MagicMock:
        raise requests.exceptions.Timeout("slow")

    with patch("src.crawler.requests.get", side_effect=fake_get), \
         patch("src.crawler.time.sleep"):
        result = Crawler().crawl("https://quotes.toscrape.com/")

    assert result == {}


def test_crawl_rejects_external_start_url() -> None:
    """Asking the crawler to start outside the allowed domain is misuse."""
    with pytest.raises(CrawlError):
        Crawler().crawl("https://example.com/")


# --------------------------------------------------------------------------- #
# Bounds                                                                      #
# --------------------------------------------------------------------------- #


def test_max_pages_caps_results() -> None:
    """``max_pages`` should stop the crawler after that many successful fetches."""
    pages = {
        "https://quotes.toscrape.com/": (
            "<html><body>"
            "<a href='/page/2/'>2</a>"
            "<a href='/page/3/'>3</a>"
            "</body></html>"
        ),
        "https://quotes.toscrape.com/page/2/": "<html>2</html>",
        "https://quotes.toscrape.com/page/3/": "<html>3</html>",
    }

    def fake_get(url: str, **_: object) -> MagicMock:
        return _make_response(200, pages[url])

    with patch("src.crawler.requests.get", side_effect=fake_get), \
         patch("src.crawler.time.sleep"):
        result = Crawler(max_pages=2).crawl("https://quotes.toscrape.com/")

    assert len(result) == 2
