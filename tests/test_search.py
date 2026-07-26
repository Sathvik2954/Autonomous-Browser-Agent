"""
Tests the HTML parsing logic against a saved fixture, since this sandbox's
network is blocked (confirmed via direct curl -- same restriction that blocked
the Playwright/Chromium download earlier in this project's history). This
verifies parse_results_html() is correct; it does NOT verify DuckDuckGo's
current live markup matches this fixture. Run a real query on a machine with
network access to confirm that part.
"""
from app.search.duckduckgo import parse_results_html, _resolve_redirect_url

# Structural shape based on DuckDuckGo's documented HTML-endpoint markup
# (div.result > a.result__a for the title/link, .result__snippet for the
# blurb, redirect links wrapping the real URL in a `uddg` query param).
FIXTURE_HTML = """
<html><body>
<div class="results">
  <div class="result results_links results_links_deep web-result">
    <div class="links_main links_deep result__body">
      <h2 class="result__title">
        <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FHyderabad&amp;rut=abc123">Hyderabad - Wikipedia</a>
      </h2>
      <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FHyderabad">Hyderabad is the capital of the Indian state of Telangana and its largest city.</a>
    </div>
  </div>
  <div class="result results_links results_links_deep web-result">
    <div class="links_main links_deep result__body">
      <h2 class="result__title">
        <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.britannica.com%2Fplace%2FHyderabad-India&amp;rut=def456">Hyderabad | History, Population, Map, &amp; Facts | Britannica</a>
      </h2>
      <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.britannica.com%2Fplace%2FHyderabad-India">Hyderabad, city, capital of Telangana state, southern India.</a>
    </div>
  </div>
  <div class="result result--ad">
    <!-- an ad card with no result__a -- must not crash or be counted -->
    <div class="links_main">no title link here</div>
  </div>
</div>
</body></html>
"""


def test_parse_results_html_extracts_title_url_snippet():
    results = parse_results_html(FIXTURE_HTML, max_results=5)
    assert len(results) == 2

    first = results[0]
    assert first.title == "Hyderabad - Wikipedia"
    assert first.url == "https://en.wikipedia.org/wiki/Hyderabad"
    assert "capital of the Indian state of Telangana" in first.snippet


def test_parse_results_html_resolves_ddg_redirect_urls():
    results = parse_results_html(FIXTURE_HTML, max_results=5)
    for r in results:
        assert not r.url.startswith("//duckduckgo.com/l/"), f"URL wasn't unwrapped: {r.url}"
        assert r.url.startswith("https://")


def test_parse_results_html_respects_max_results():
    results = parse_results_html(FIXTURE_HTML, max_results=1)
    assert len(results) == 1


def test_parse_results_html_skips_malformed_cards_without_crashing():
    # The fixture includes an ad card with no result__a link -- should be
    # silently skipped, not raise or produce a broken/empty-title result.
    results = parse_results_html(FIXTURE_HTML, max_results=10)
    assert all(r.title and r.url for r in results)


def test_parse_results_html_handles_empty_page():
    assert parse_results_html("<html><body>no results here</body></html>") == []


def test_resolve_redirect_url_unwraps_uddg_param():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=xyz"
    assert _resolve_redirect_url(href) == "https://example.com/page"


def test_resolve_redirect_url_passes_through_direct_links():
    href = "https://example.com/already-a-real-link"
    assert _resolve_redirect_url(href) == href
