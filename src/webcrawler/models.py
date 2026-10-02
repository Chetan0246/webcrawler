"""Async SQLite persistence for crawled pages."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    host TEXT NOT NULL,
    status INTEGER,
    title TEXT,
    text_len INTEGER DEFAULT 0,
    content_markdown TEXT,
    content_type TEXT,
    fetched_at TEXT NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_pages_host ON pages(host);
CREATE TABLE IF NOT EXISTS links (
    src INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    dst TEXT NOT NULL,
    PRIMARY KEY (src, dst)
);
"""


@dataclass(slots=True)
class PageRecord:
    url: str
    host: str
    status: int | None
    title: str | None
    text_len: int
    content_type: str | None
    content_markdown: str | None = None
    error: str | None = None


class Store:
    """Thin async wrapper over SQLite."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._db: aiosqlite.Connection | None = None

    async def __aenter__(self) -> Store:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        try:
            await self._db.execute("ALTER TABLE pages ADD COLUMN content_markdown TEXT")
        except Exception:
            pass
        await self._db.commit()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @asynccontextmanager
    async def tx(self) -> AsyncIterator[aiosqlite.Connection]:
        assert self._db is not None, "use 'async with Store(...) as store'"
        yield self._db
        await self._db.commit()

    async def is_known(self, url: str) -> bool:
        async with self.tx() as db:
            row = await db.execute("SELECT 1 FROM pages WHERE url = ?", (url,))
            return await row.fetchone() is not None

    async def seen_urls(self) -> set[str]:
        async with self.tx() as db:
            cur = await db.execute("SELECT url FROM pages")
            return {row[0] for row in await cur.fetchall()}

    async def save_page(self, rec: PageRecord, links: list[str]) -> None:
        async with self.tx() as db:
            cur = await db.execute(
                """INSERT INTO pages
                       (url, host, status, title, text_len, content_markdown, content_type, fetched_at, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                     status=excluded.status,
                     title=excluded.title,
                     text_len=excluded.text_len,
                     content_markdown=excluded.content_markdown,
                     content_type=excluded.content_type,
                     fetched_at=excluded.fetched_at,
                     error=excluded.error""",
                (
                    rec.url,
                    rec.host,
                    rec.status,
                    rec.title,
                    rec.text_len,
                    rec.content_markdown,
                    rec.content_type,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    rec.error,
                ),
            )
            page_id = cur.lastrowid
            if links and page_id:
                await db.executemany(
                    "INSERT OR IGNORE INTO links (src, dst) VALUES (?, ?)",
                    [(page_id, link) for link in links],
                )

    async def top_pages(self, limit: int = 20) -> list[aiosqlite.Row]:
        async with self.tx() as db:
            cur = await db.execute(
                "SELECT url, status, title, text_len FROM pages ORDER BY text_len DESC LIMIT ?",
                (limit,),
            )
            return list(await cur.fetchall())

    async def get_all_successful_pages(self) -> list[aiosqlite.Row]:
        async with self.tx() as db:
            cur = await db.execute(
                "SELECT url, host, status, title, text_len, content_markdown, fetched_at FROM pages WHERE status = 200"
            )
            return list(await cur.fetchall())

    async def stats(self) -> dict[str, int]:
        async with self.tx() as db:
            cur = await db.execute(
                "SELECT COUNT(*), COALESCE(SUM(status >= 200 AND status < 300), 0), "
                "COALESCE(SUM(status IS NULL OR status >= 400), 0) FROM pages"
            )
            total, ok, failed = (await cur.fetchone()) or (0, 0, 0)
            return {"total": total, "ok": ok, "failed": failed}
