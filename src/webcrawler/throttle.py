"""Per-host politeness: token-bucket rate limiting with crawl-delay support."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit


class HostThrottle:
    """Async per-host rate limiter: min delay between requests per host."""

    def __init__(self, default_delay: float = 1.0) -> None:
        self.default_delay = default_delay
        self._next_slot: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def set_delay(self, host: str, delay: float) -> None:
        """Respect a host's advertised crawl-delay (never below default)."""
        self._per_host_delay[host] = max(self.default_delay, delay)

    @property
    def _per_host_delay(self) -> dict[str, float]:
        if not hasattr(self, "_delays"):
            self._delays: dict[str, float] = {}
        return self._delays

    async def wait(self, url: str) -> float:
        """Reserve the next slot for this URL's host; returns seconds waited."""
        host = urlsplit(url).netloc.lower()
        async with self._lock:
            now = time.monotonic()
            delay = self._per_host_delay.get(host, self.default_delay)
            scheduled = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = scheduled + delay
        wait_for = scheduled - now
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        return max(0.0, wait_for)


class DomainFilter:
    """Restrict crawling to a set of allowed domains (suffix match)."""

    def __init__(self, allowed_domains: set[str], follow_external: bool = False) -> None:
        self.allowed = {
            self._normalize_domain(d) for d in allowed_domains if self._normalize_domain(d)
        }
        self.follow_external = follow_external

    def allows(self, url: str) -> bool:
        if self.follow_external:
            return True
        host = urlsplit(url).netloc.lower().split(":")[0]
        return any(host == d or host.endswith("." + d) for d in self.allowed)

    def _normalize_domain(self, domain: str) -> str:
        """Strip scheme/port/path so seeds like 'https://example.com/' match."""
        host = urlsplit(domain if "://" in domain else "//" + domain, scheme="https").netloc
        return host.lower().split(":")[0].lstrip(".")
