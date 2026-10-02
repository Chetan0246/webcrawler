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
