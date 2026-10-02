"""robots.txt fetching, parsing and caching (per host)."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field

import aiohttp


@dataclass(slots=True)
class RobotsRules:
    disallow: list[str] = field(default_factory=list)
    allow: list[str] = field(default_factory=list)
    crawl_delay: float | None = None
    fetched_ok: bool = False

    def is_allowed(self, path: str) -> bool:
        """Longest-match semantics: more specific rule wins; Allow wins ties."""
        best_len = -1
        best_allow = True
        for prefix in self.allow:
            if path.startswith(prefix) and len(prefix) > best_len:
                best_len, best_allow = len(prefix), True
        for prefix in self.disallow:
            if path.startswith(prefix) and len(prefix) > best_len:
                best_len, best_allow = len(prefix), False
        return best_allow


class RobotsCache:
    """Fetches and caches RobotsRules per scheme+host."""

    def __init__(
        self, session: aiohttp.ClientSession, user_agent: str, timeout: float = 10.0
    ) -> None:
        self._session = session
        self._ua = user_agent
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._cache: dict[str, RobotsRules] = {}

    async def for_url(self, url: str) -> RobotsRules:
        parsed = urllib.parse.urlsplit(url)
        key = f"{parsed.scheme}://{parsed.netloc}"
        if key in self._cache:
            return self._cache[key]

        rules = RobotsRules()
        robots_url = f"{key}/robots.txt"
        try:
            async with self._session.get(robots_url, timeout=self._timeout) as resp:
                if resp.status == 200:
                    body = (await resp.text(errors="replace")).splitlines()
                    rules = _parse_robots(body, self._ua)
                    rules.fetched_ok = True
        except aiohttp.ClientError:
            pass  # unreachable robots -> treat as unrestricted
        self._cache[key] = rules
        return rules


def _parse_robots(lines: list[str], user_agent: str) -> RobotsRules:
    """Group-based robots.txt parser.

    Collects every `User-agent: ...` that starts a group, then applies the
    group's rules. A group whose agent list contains our UA token overrides
    the `*` group; otherwise `*` applies.
    """
    ua_token = user_agent.split("/")[0].strip().lower()

    @dataclass
    class _Group:
        agents: list[str] = field(default_factory=list)
        rules: RobotsRules = field(default_factory=RobotsRules)

    groups: list[_Group] = []
    current: _Group | None = None
    last_key_was_agent = False

    for raw in lines:
        line = raw.split("#")[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()

        if key == "user-agent":
            if not last_key_was_agent or current is None:
                current = _Group()
                groups.append(current)
            current.agents.append(value.lower())
            last_key_was_agent = True
            continue

        last_key_was_agent = False
        if current is None or not value:
            continue

        rules = current.rules
        if key == "disallow":
            rules.disallow.append(value)
        elif key == "allow":
            rules.allow.append(value)
        elif key == "crawl-delay":
            try:
                rules.crawl_delay = max(rules.crawl_delay or 0.0, float(value))
            except ValueError:
                pass

    for group in groups:
        if ua_token in group.agents:
            group.rules.fetched_ok = True
            return group.rules
    for group in groups:
        if "*" in group.agents:
            group.rules.fetched_ok = True
            return group.rules
    return RobotsRules()  # no rules at all -> unrestricted
