"""Polite breadth-first web crawler for ``quotes.toscrape.com``.

The :class:`Crawler` performs a breadth-first traversal starting from a given
URL, following only links inside the configured allowed domain, sleeping for a
mandatory politeness window between requests, and tolerating individual page
failures (timeouts, connection errors, non-200 responses) without aborting the
whole crawl.

The crawler intentionally does **no** parsing beyond extracting links — the
HTML it returns is handed off to :mod:`src.indexer` for tokenisation. Keeping
the two concerns separate means we can build and test the index from cached
HTML fixtures without ever hitting the network.
"""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from typing import Callable, Dict, Iterable, Optional, Set
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.config import (
    ALLOWED_DOMAIN,
    POLITENESS_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
)

logger = logging.getLogger(__name__)

# Path prefixes that exist on the live site but never carry quote content.
# Indexing them just dilutes TF-IDF with login-form boilerplate.
_NON_CONTENT_PATHS: tuple[str, ...] = ("/login", "/logout")

# Matches a trailing ``/page/1/`` (or ``/page/1``) segment. The first page of
# any listing is always served at the un-suffixed URL too, so collapsing them
# avoids indexing the same content twice.
_PAGE_ONE_SUFFIX = re.compile(r"/page/1/?$")


class CrawlError(Exception):
    """Raised when the crawler encounters a fatal, non-recoverable problem.

    Per-page failures are *not* fatal — they are logged and skipped. This
    exception is reserved for misuse (for example, being asked to crawl a URL
    outside the allowed domain).
    """


class Crawler:
    """Breadth-first crawler with a mandatory politeness window.

    Attributes:
        allowed_domain: Domain that the crawler is permitted to follow links
            into. Links to any other host are silently dropped.
        delay: Seconds to wait between successive HTTP requests. Defaults to
            :data:`src.config.POLITENESS_DELAY_SECONDS` (six seconds).
        timeout: Per-request timeout in seconds.
        user_agent: ``User-Agent`` header sent with every request.
        max_pages: Optional safety cap on the number of pages to fetch. ``None``
            means crawl until the frontier is exhausted.
    """

    def __init__(
        self,
        allowed_domain: str = ALLOWED_DOMAIN,
        delay: float = POLITENESS_DELAY_SECONDS,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        user_agent: str = USER_AGENT,
        max_pages: Optional[int] = None,
    ) -> None:
        if delay < POLITENESS_DELAY_SECONDS:
            # Guard against accidentally being too fast against the live site.
            # Tests can monkeypatch ``POLITENESS_DELAY_SECONDS`` if they need
            # to exercise a different value, but the *default* must respect
            # the brief.
            raise CrawlError(
                f"delay must be >= {POLITENESS_DELAY_SECONDS} seconds "
                f"(got {delay})"
            )
        self.allowed_domain = allowed_domain
        self.delay = delay
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_pages = max_pages

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def crawl(
        self,
        start_url: str,
        on_page: Optional[Callable[[str, int], None]] = None,
    ) -> Dict[str, str]:
        """Crawl outward from ``start_url`` and return ``{url: html}``.

        Args:
            start_url: Seed URL. Must live on :attr:`allowed_domain`.
            on_page: Optional callback invoked after each successful fetch
                with ``(url, page_count)``. Used by the CLI to stream
                progress to the user during the long politeness-bound crawl.

        Returns:
            Mapping from canonicalised URL to the raw HTML body of the page.
            Pages that returned a non-200 status, timed out, or otherwise
            failed are omitted.

        Raises:
            CrawlError: If ``start_url`` is outside the allowed domain.
        """
        start_url = self._canonicalise(start_url)
        if not self._is_internal(start_url):
            raise CrawlError(
                f"start_url {start_url!r} is outside allowed domain "
                f"{self.allowed_domain!r}"
            )

        results: Dict[str, str] = {}
        visited: Set[str] = set()
        frontier: "deque[str]" = deque([start_url])
        request_count = 0

        while frontier:
            if self.max_pages is not None and len(results) >= self.max_pages:
                logger.info("Reached max_pages cap (%d); stopping.", self.max_pages)
                break

            url = frontier.popleft()
            if url in visited:
                continue
            visited.add(url)

            # Politeness window. We sleep *before* every request except the
            # very first one, so a one-page crawl issues exactly one request
            # with no leading delay.
            if request_count > 0:
                logger.debug("Sleeping %.1fs before fetching %s", self.delay, url)
                time.sleep(self.delay)

            html = self._fetch(url)
            request_count += 1
            if html is None:
                # Failure already logged inside _fetch.
                continue

            results[url] = html
            if on_page is not None:
                on_page(url, len(results))

            for link in self._extract_links(html, base_url=url):
                if link not in visited:
                    frontier.append(link)

        logger.info(
            "Crawl finished: %d pages fetched, %d requests issued.",
            len(results),
            request_count,
        )
        return results

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    def _fetch(self, url: str) -> Optional[str]:
        """Fetch ``url`` and return its body, or ``None`` on any failure."""
        headers = {"User-Agent": self.user_agent}
        try:
            response = requests.get(url, headers=headers, timeout=self.timeout)
        except requests.exceptions.Timeout:
            logger.warning("Timeout fetching %s; skipping.", url)
            return None
        except requests.exceptions.ConnectionError as exc:
            logger.warning("Connection error fetching %s: %s; skipping.", url, exc)
            return None
        except requests.exceptions.RequestException as exc:
            logger.warning("Request failed for %s: %s; skipping.", url, exc)
            return None

        if response.status_code != 200:
            logger.info(
                "Non-200 response (%d) for %s; skipping.",
                response.status_code,
                url,
            )
            return None

        return response.text

    def _extract_links(self, html: str, base_url: str) -> Iterable[str]:
        """Yield canonicalised, in-domain, content links found in ``html``."""
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:  # noqa: BLE001 — BS4 rarely raises, but never trust the network
            logger.warning("Failed to parse HTML from %s: %s; skipping links.", base_url, exc)
            return
        for anchor in soup.find_all("a", href=True):
            raw = anchor["href"]
            if not raw or raw.startswith(("mailto:", "javascript:", "tel:")):
                continue
            absolute = urljoin(base_url, raw)
            absolute = self._canonicalise(absolute)
            if not self._is_internal(absolute):
                continue
            if self._is_non_content(absolute):
                continue
            yield absolute

    @staticmethod
    def _is_non_content(url: str) -> bool:
        """Return ``True`` for paths that exist but carry no indexable quotes."""
        path = urlparse(url).path
        return any(path == p or path.startswith(p + "/") for p in _NON_CONTENT_PATHS)

    def _is_internal(self, url: str) -> bool:
        """Return ``True`` if ``url`` is on the allowed domain."""
        host = urlparse(url).netloc.lower()
        return host == self.allowed_domain.lower()

    @staticmethod
    def _canonicalise(url: str) -> str:
        """Normalise a URL so equivalent variants compare equal.

        Specifically:

        * fragments (``#section``) are dropped — they refer to anchors
          within the same document;
        * scheme and host are lowercased — DNS is case-insensitive;
        * a trailing ``/page/1/`` is stripped — the live site serves the
          first page of every listing at the un-suffixed URL too, so
          ``/`` and ``/page/1/`` (or ``/tag/love/`` and
          ``/tag/love/page/1/``) point at byte-identical content. Without
          this collapse those duplicates would be indexed twice and skew
          term frequencies.
        """
        url, _ = urldefrag(url)
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        scheme = parsed.scheme.lower() or "https"
        path = _PAGE_ONE_SUFFIX.sub("/", parsed.path) if parsed.path else parsed.path
        rebuilt = parsed._replace(scheme=scheme, netloc=netloc, path=path).geturl()
        return rebuilt
