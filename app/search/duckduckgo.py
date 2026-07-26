"""
Structured web search via DuckDuckGo's HTML endpoint, instead of driving the
browser through google.com's DOM to search. AgenticSeek gets the same benefit
by bundling SearXNG behind Docker; this gets most of the value (a plain HTTP
request returning structured {title, url, snippet} results instead of several
brittle DOM-interaction steps) with zero extra infrastructure -- no Docker, no
API key, nothing to keep running as a service.

CAVEAT, same as the Maps/Amazon selectors from earlier: this was NOT verified
against the live endpoint in this session -- this sandbox's outbound network is
blocked (confirmed via a direct curl, same restriction that blocked the
Playwright/Chromium download). The parsing logic is verified against a saved
HTML fixture in tests/test_search.py instead. If a real query on your machine
comes back with zero results, DuckDuckGo's HTML markup has likely shifted and
the selectors in parse_results_html() need a look -- that function is
deliberately split out from search_web() so you can test a fresh fixture
without needing to touch the network code.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SEARCH_URL = "https://html.duckduckgo.com/html/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 10


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchError(Exception):
    pass


def _resolve_redirect_url(href: str) -> str:
    """DuckDuckGo's HTML results wrap the real destination in a redirect link
    like '//duckduckgo.com/l/?uddg=<url-encoded-real-url>&rut=...' -- unwrap it
    so callers get the actual destination to navigate to, not a DDG redirect
    the browser would have to follow separately."""
    if not href:
        return href
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path == "/l/":
        query_params = parse_qs(parsed.query)
        real_url = query_params.get("uddg", [None])[0]
        if real_url:
            return unquote(real_url)
    return href


def parse_results_html(html: str, max_results: int = 5) -> list:
    """Split out from search_web() specifically so this can be unit tested
    against a saved HTML fixture, without making a real network call."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for result_div in soup.select("div.result"):
        title_tag = result_div.select_one("a.result__a")
        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)
        url = _resolve_redirect_url(title_tag.get("href", ""))
        if not title or not url:
            continue

        snippet_tag = result_div.select_one(".result__snippet")
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

        results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break

    return results


def search_web(query: str, max_results: int = 5) -> list:
    """Returns a list[SearchResult]. Raises SearchError on a network failure
    rather than returning an empty list -- an empty list should mean "genuinely
    no results," not "couldn't reach the search engine," since the caller
    (the agent's action loop) needs to tell those two apart to react sensibly."""
    if not query or not query.strip():
        return []

    try:
        response = requests.post(
            SEARCH_URL,
            data={"q": query},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise SearchError(f"Search request for '{query}' failed: {e}")

    return parse_results_html(response.text, max_results=max_results)
