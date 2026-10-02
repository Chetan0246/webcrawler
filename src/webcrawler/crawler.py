"""Crawler engine: BFS frontier, robots compliance, politeness, persistence."""

from __future__ import annotations

import asyncio
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from webcrawler.models import PageRecord, Store
from webcrawler.robots import RobotsCache
from webcrawler.throttle import DomainFilter, HostThrottle

USER_AGENT = "advanced-webcrawler/1.0 (+respectful; python-aiohttp)"
MAX_PAGE_BYTES = 2 * 1024 * 1024  # 2 MiB safety cap

SKIP_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".css",
    ".js",
}


@dataclass(slots=True)
class CrawlConfig:
    start_urls: list[str]
    max_pages: int = 50
    max_depth: int = 3
    concurrency: int = 8
    delay: float = 1.0
    timeout: float = 15.0
    follow_external: bool = False


@dataclass(slots=True)
class CrawlReport:
    fetched: int = 0
    failed: int = 0
    skipped_robots: int = 0
    skipped_domain: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fetched": self.fetched,
            "failed": self.failed,
            "skipped_robots": self.skipped_robots,
            "skipped_domain": self.skipped_domain,
            "duplicates": self.duplicates,
        }


class Crawler:
    """Polite async crawler writing results into a Store."""

    def __init__(self, config: CrawlConfig, store: Store) -> None:
        self.config = config
        self.store = store
        self.report = CrawlReport()

        self.throttle = HostThrottle(default_delay=config.delay)
        self.domain_filter = DomainFilter(
            {urllib.parse.urlsplit(u).netloc for u in config.start_urls},
            follow_external=config.follow_external,
        )
        self._session: aiohttp.ClientSession | None = None
        self._robots: RobotsCache | None = None
        self._seen: set[str] = set()
        self._in_flight = 0
        self._done_event = asyncio.Event()
        self._progress_cb: Any = None

    def on_progress(self, cb: Any) -> None:
        self._progress_cb = cb

    # ------------------------------------------------------------ utilities ---
    @staticmethod
    def normalize(url: str) -> str:
        p = urllib.parse.urlsplit(url)
        path = p.path or "/"
        return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))

    @staticmethod
    def is_crawlable(url: str) -> bool:
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("http", "https"):
            return False
        ext = urllib.parse.urlsplit(url).path.lower()
        return not any(ext.endswith(e) for e in SKIP_EXTENSIONS)

    # ------------------------------------------------------------ main loop ---
    async def run(self) -> CrawlReport:
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        connector = aiohttp.TCPConnector(limit=self.config.concurrency, ttl_dns_cache=300)
        async with aiohttp.ClientSession(
            timeout=timeout, connector=connector, headers={"User-Agent": USER_AGENT}
        ) as session:
            self._session = session
            self._robots = RobotsCache(session, USER_AGENT)
            queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()

            for url in self.config.start_urls:
                normalized = self.normalize(url)
                if self.domain_filter.allows(normalized) and self.is_crawlable(normalized):
                    queue.put_nowait((normalized, 0))
                    self._seen.add(normalized)

            workers = [
                asyncio.create_task(self._worker(queue)) for _ in range(self.config.concurrency)
            ]
            await queue.join()
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        return self.report

    async def _worker(self, queue: asyncio.Queue[tuple[str, int]]) -> None:
        while True:
            url, depth = await queue.get()
            try:
                await self._process(url, depth, queue)
            finally:
                queue.task_done()

    async def _process(self, url: str, depth: int, queue: asyncio.Queue[tuple[str, int]]) -> None:
        if self.report.fetched + self.report.failed >= self.config.max_pages:
            return

        # robots.txt gate
        assert self._robots is not None
        rules = await self._robots.for_url(url)
        path = urllib.parse.urlsplit(url).path or "/"
        if rules.fetched_ok and not rules.is_allowed(path):
            self.report.skipped_robots += 1
            return
        if rules.crawl_delay:
            self.throttle.set_delay(urllib.parse.urlsplit(url).netloc, rules.crawl_delay)

        await self.throttle.wait(url)

        assert self._session is not None
        try:
            async with self._session.get(url, allow_redirects=True) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if resp.status != 200 or "text/html" not in ctype:
                    self.report.failed += 1
                    await self.store.save_page(
                        PageRecord(
                            url=url,
                            host=urllib.parse.urlsplit(url).netloc,
                            status=resp.status,
                            title=None,
                            text_len=0,
                            content_type=ctype,
                        ),
                        links=[],
                    )
                    return
                body = await resp.content.read(MAX_PAGE_BYTES)

            title, text_len, links = self._extract(body, url)
            await self.store.save_page(
                PageRecord(
                    url=url,
                    host=urllib.parse.urlsplit(url).netloc,
                    status=200,
                    title=title,
                    text_len=text_len,
                    content_type="text/html",
                ),
                links=links,
            )
            self.report.fetched += 1
            if self._progress_cb:
                self._progress_cb(url, title, self.report.fetched)

            # enqueue children
            if depth + 1 <= self.config.max_depth:
                for link in links:
                    norm = self.normalize(link)
                    if norm in self._seen:
                        self.report.duplicates += 1
                        continue
                    self._seen.add(norm)
                    if not self.domain_filter.allows(norm):
                        self.report.skipped_domain += 1
                        continue
                    if not self.is_crawlable(norm):
                        continue
                    if self.report.fetched + self.report.failed >= self.config.max_pages:
                        break
                    queue.put_nowait((norm, depth + 1))
        except aiohttp.ClientError as exc:
            self.report.failed += 1
            self.report.errors.append(f"{url}: {exc}")
            await self.store.save_page(
                PageRecord(
                    url=url,
                    host=urllib.parse.urlsplit(url).netloc,
                    status=None,
                    title=None,
                    text_len=0,
                    content_type=None,
                    error=str(exc),
                ),
                links=[],
            )

    # ------------------------------------------------------------- parsing ---
    @staticmethod
    def _extract(body: bytes, base_url: str) -> tuple[str | None, int, list[str]]:
        soup = BeautifulSoup(body, "lxml")
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        text_len = len(soup.get_text(" ", strip=True))

        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            absolute = urllib.parse.urljoin(base_url, anchor["href"])
            if urllib.parse.urlsplit(absolute).scheme in ("http", "https"):
                links.append(absolute.split("#")[0])
        return title, text_len, links
