"""Unit tests for crawler components (network-free)."""

from __future__ import annotations

import asyncio

from webcrawler.crawler import Crawler
from webcrawler.robots import _parse_robots
from webcrawler.throttle import DomainFilter, HostThrottle


def test_robots_parses_star_group() -> None:
    lines = [
        "User-agent: *",
        "Disallow: /private/",
        "Allow: /private/public",
        "Crawl-delay: 2.5",
    ]
    rules = _parse_robots(lines, "advanced-webcrawler/1.0")
    assert rules.fetched_ok
    assert rules.crawl_delay == 2.5
    assert not rules.is_allowed("/private/secret")
    assert rules.is_allowed("/private/public/page")
    assert rules.is_allowed("/everything-else")


def test_robots_specific_agent_overrides_star() -> None:
    lines = [
        "User-agent: *",
        "Disallow: /",
        "",
        "User-agent: advanced-webcrawler",
        "Allow: /",
        "Disallow: /admin",
    ]
    rules = _parse_robots(lines, "advanced-webcrawler/1.0")
    assert rules.is_allowed("/blog/post")
    assert not rules.is_allowed("/admin/panel")


def test_normalize_strips_fragments() -> None:
    assert Crawler.normalize("HTTPS://Example.COM/path?q=1#frag") == "https://example.com/path?q=1"


def test_is_crawlable_filters_assets() -> None:
    assert Crawler.is_crawlable("https://x.com/a/b.html")
    assert not Crawler.is_crawlable("https://x.com/img.png")
    assert not Crawler.is_crawlable("ftp://x.com/file")


def test_domain_filter_blocks_external() -> None:
    f = DomainFilter({"example.com"})
    assert f.allows("https://example.com/page")
    assert f.allows("https://sub.example.com/page")
    assert not f.allows("https://other.org/page")


async def test_throttle_spaces_requests_per_host() -> None:
    t = HostThrottle(default_delay=0.05)
    await t.wait("https://a.com/1")
    start = asyncio.get_running_loop().time()
    await t.wait("https://a.com/2")
    waited = asyncio.get_running_loop().time() - start
    assert waited >= 0.04  # spaced by ~delay
    # different host is not delayed
    start = asyncio.get_running_loop().time()
    await t.wait("https://b.com/1")
    assert asyncio.get_running_loop().time() - start < 0.04


def test_extract_clean_markdown() -> None:
    html = b"""
    <!DOCTYPE html>
    <html>
      <head><title>Test Article</title></head>
      <body>
        <nav><a href="/home">Home</a></nav>
        <h1>Main Headline</h1>
        <p>This is the first paragraph with a <a href="https://example.com/learn">link</a>.</p>
        <ul>
          <li>Feature A</li>
          <li>Feature B</li>
        </ul>
        <script>console.log('remove me');</script>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """
    title, text_len, links, markdown = Crawler._extract(html, "https://example.com")
    assert title == "Test Article"
    assert text_len > 0
    assert "https://example.com/learn" in links
    assert "# Main Headline" in markdown
    assert "Feature A" in markdown
    assert "console.log" not in markdown
    assert "Copyright 2026" not in markdown


async def test_store_saves_and_retrieves_markdown(tmp_path) -> None:
    from pathlib import Path
    from webcrawler.models import PageRecord, Store

    db_path = tmp_path / "test_crawl.db"
    async with Store(db_path) as store:
        rec = PageRecord(
            url="https://example.com/page",
            host="example.com",
            status=200,
            title="Example Title",
            text_len=150,
            content_type="text/html",
            content_markdown="# Example\n\nContent body here.",
        )
        await store.save_page(rec, ["https://example.com/sub"])
        assert await store.is_known("https://example.com/page")
        pages = await store.get_all_successful_pages()
        assert len(pages) == 1
        assert pages[0]["title"] == "Example Title"
        assert pages[0]["content_markdown"] == "# Example\n\nContent body here."

