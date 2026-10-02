# webcrawler

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-blue)](.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB)](pyproject.toml)

Polite async web crawler built on **aiohttp** + **BeautifulSoup**, with a BFS
frontier, per-host rate limiting, robots.txt compliance and SQLite persistence.

## Features

- Concurrent workers over an `asyncio.Queue` BFS frontier
- **Clean Markdown Extraction:** Automatically extracts clean article Markdown from HTML, ready for RAG pipelines and LLMs
- **Export Formats:** Direct export to individual `.md` Markdown files (`--export-markdown`) or JSONL (`--export-jsonl`)
- **Politeness & Backoff:** Per-host token spacing (`HostThrottle`), robots.txt compliance, and automatic HTTP 429/503 retry backoff
- Domain-restricted crawling (suffix match), external links opt-in
- Normalization (fragment stripping, lowercase scheme/host), asset filtering
- SQLite store: `pages` + `links` tables with `content_markdown` column
- Rich progress + final report

## Usage

```bash
cd webcrawler
python -m venv .venv && source .venv/Scripts/activate
pip install -e ".[dev]"

# Crawl and export clean Markdown files for LLM/RAG pipelines
webcrawler crawl https://example.com \
  --db crawl.db --max-pages 25 --max-depth 2 --delay 0.5 \
  --export-markdown ./crawled_md \
  --export-jsonl ./crawled.jsonl

# Export previously crawled database to Markdown/JSONL
webcrawler export --db crawl.db --export-markdown ./exported_md
```

Explore results:

```bash
sqlite3 crawl.db "SELECT url, title, text_len, SUBSTR(content_markdown, 1, 100) FROM pages LIMIT 10;"
sqlite3 crawl.db "SELECT dst, COUNT(*) c FROM links GROUP BY dst ORDER BY c DESC LIMIT 10;"
```

## Tests (network-free)

```bash
pytest
```
