# webcrawler

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-blue)](.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB)](pyproject.toml)

Polite async web crawler built on **aiohttp** + **BeautifulSoup**, with a BFS
frontier, per-host rate limiting, robots.txt compliance and SQLite persistence.

## Features

- Concurrent workers over an `asyncio.Queue` BFS frontier
- Per-host token spacing (`HostThrottle`) honoring `Crawl-delay`
- robots.txt group-based parser with Allow/Disallow longest-match
- Domain-restricted crawling (suffix match), external links opt-in
- Normalization (fragment stripping, lowercase scheme/host), asset filtering
- SQLite store: `pages` + `links` tables, upsert on revisit
- Rich progress + final report

## Usage

```bash
cd webcrawler
python -m venv .venv && source .venv/Scripts/activate
pip install -e ".[dev]"

webcrawler crawl https://example.com https://httpbin.org/links/3/2 \
  --db crawl.db --max-pages 25 --max-depth 2 --delay 0.5
```

Explore results:

```bash
sqlite3 crawl.db "SELECT url, title, text_len FROM pages ORDER BY text_len DESC LIMIT 10;"
sqlite3 crawl.db "SELECT dst, COUNT(*) c FROM links GROUP BY dst ORDER BY c DESC LIMIT 10;"
```

## Tests (network-free)

```bash
pytest
```
