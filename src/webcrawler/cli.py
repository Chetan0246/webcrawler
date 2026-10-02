"""Typer CLI for webcrawler."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

# Windows consoles default to cp1252; never crash on unicode spinner/box chars.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="replace")
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from webcrawler.crawler import CrawlConfig, Crawler
from webcrawler.models import Store

app = typer.Typer(help="Polite async web crawler.", no_args_is_help=True, add_completion=False)
console = Console()


def _sanitize_filename(name: str) -> str:
    clean = re.sub(r'[\/:*?"<>|]+', "_", name)
    return clean[:120].strip("._") or "page"


def _export_data(
    pages: list[Any],
    export_markdown: Path | None = None,
    export_jsonl: Path | None = None,
) -> None:
    if not pages:
        return

    if export_jsonl:
        export_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with export_jsonl.open("w", encoding="utf-8") as f:
            for row in pages:
                rec = {
                    "url": row["url"],
                    "host": row["host"],
                    "title": row["title"],
                    "text_len": row["text_len"],
                    "markdown": row["content_markdown"],
                    "fetched_at": row["fetched_at"],
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        msg = f"Exported {len(pages)} pages to JSONL: {export_jsonl}"
        console.print(f"[green]{msg}[/green]")

    if export_markdown:
        export_markdown.mkdir(parents=True, exist_ok=True)
        for i, row in enumerate(pages):
            base_name = row["title"] or row["url"].split("//")[-1]
            file_name = f"{i + 1:03d}_{_sanitize_filename(base_name)}.md"
            file_path = export_markdown / file_name
            fallback = f"# {row['title'] or row['url']}\n\n(No text content)"
            content = row["content_markdown"] or fallback
            file_path.write_text(content, encoding="utf-8")
        msg = f"Exported {len(pages)} Markdown files to: {export_markdown}"
        console.print(f"[green]{msg}[/green]")


@app.command()
def crawl(
    start_urls: list[str] = typer.Argument(..., help="Seed URLs"),
    db: Path = typer.Option(Path("crawl.db"), "--db", "-d", help="SQLite output database"),
    max_pages: int = typer.Option(50, "--max-pages", "-n", min=1, help="Maximum pages to fetch"),
    max_depth: int = typer.Option(3, "--max-depth", min=0, help="Maximum link depth"),
    concurrency: int = typer.Option(8, "--concurrency", "-c", min=1, max=64),
    delay: float = typer.Option(1.0, "--delay", help="Min seconds between requests per host"),
    follow_external: bool = typer.Option(
        False, "--follow-external", help="Crawl off-site links too"
    ),
    export_markdown: Path | None = typer.Option(
        None, "--export-markdown", "-m", help="Directory to export clean Markdown files"
    ),
    export_jsonl: Path | None = typer.Option(
        None, "--export-jsonl", "-j", help="Path to export pages as JSONL"
    ),
) -> None:
    """Crawl the web starting from START_URLS, storing results in DB and optional exports."""
    config = CrawlConfig(
        start_urls=list(start_urls),
        max_pages=max_pages,
        max_depth=max_depth,
        concurrency=concurrency,
        delay=delay,
        follow_external=follow_external,
    )

    async def _run() -> tuple[Crawler, list[Any]]:
        async with Store(db) as store:
            crawler = Crawler(config, store)

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("crawling", total=max_pages)

                def on_progress(url: str, title: str | None, count: int) -> None:
                    progress.update(task, completed=count, description=f"crawling … {url[:60]}")

                crawler.on_progress(on_progress)
                await crawler.run()

            pages = []
            if export_markdown or export_jsonl:
                pages = await store.get_all_successful_pages()

            return crawler, pages

    crawler, pages = asyncio.run(_run())
    if export_markdown or export_jsonl:
        _export_data(pages, export_markdown=export_markdown, export_jsonl=export_jsonl)

    report = crawler.report.as_dict()
    table = Table(title="Crawl report", header_style="bold magenta")
    for k, v in report.items():
        table.add_row(k, str(v))
    console.print(table)
    console.print(f"Results stored in [bold]{db}[/bold] — explore with:")
    query_cmd = f'  sqlite3 "{db}" "SELECT url, title, text_len FROM pages LIMIT 20;"'
    console.print(query_cmd)


@app.command()
def export(
    db: Path = typer.Option(Path("crawl.db"), "--db", "-d", help="SQLite database to export from"),
    export_markdown: Path | None = typer.Option(
        None, "--export-markdown", "-m", help="Directory to export clean Markdown files"
    ),
    export_jsonl: Path | None = typer.Option(
        None, "--export-jsonl", "-j", help="Path to export pages as JSONL"
    ),
) -> None:
    """Export crawled pages from SQLite into Markdown or JSONL."""
    if not db.exists():
        console.print(f"[red]Error: database {db} does not exist.[/red]")
        raise typer.Exit(code=1)

    async def _fetch() -> list[Any]:
        async with Store(db) as store:
            return await store.get_all_successful_pages()

    pages = asyncio.run(_fetch())
    _export_data(pages, export_markdown=export_markdown, export_jsonl=export_jsonl)


if __name__ == "__main__":
    app()
