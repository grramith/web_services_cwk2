"""Project-wide configuration constants.

Centralising these values here makes them easy to discover, easy to override
in tests, and ensures a single source of truth for things like the politeness
delay and the default index location.
"""

from __future__ import annotations

from typing import Final

#: Base URL of the website that is allowed to be crawled.
BASE_URL: Final[str] = "https://quotes.toscrape.com/"

#: Domain of the website. Used to filter out external links during crawling.
ALLOWED_DOMAIN: Final[str] = "quotes.toscrape.com"

#: Mandatory politeness delay between successive HTTP requests, in seconds.
#:
#: The coursework brief requires a minimum of six seconds between hits to
#: ``quotes.toscrape.com``. Do not lower this value when running against the
#: live site.
POLITENESS_DELAY_SECONDS: Final[float] = 6.0

#: HTTP request timeout, in seconds. Keeps a misbehaving server from stalling
#: the crawler indefinitely.
REQUEST_TIMEOUT_SECONDS: Final[float] = 10.0

#: User-Agent string sent with every request so the operator of the target
#: site can identify (and contact) us if the crawler misbehaves.
USER_AGENT: Final[str] = (
    "COMP3011-QuotesSearchEngine/0.1 "
    "(University of Leeds coursework crawler; contact via module repository)"
)

#: Default location of the persisted inverted index on disk.
DEFAULT_INDEX_PATH: Final[str] = "data/index.json"
