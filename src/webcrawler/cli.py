"""Typer CLI for webcrawler."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

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
) -> None:
    """Crawl the web starting from START_URLS, storing results in DB."""
    config = CrawlConfig(
        start_urls=list(start_urls),
        max_pages=max_pages,
        max_depth=max_depth,
        concurrency=concurrency,
        delay=delay,
        follow_external=follow_external,
    )

    async def _run() -> tuple[Crawler, Store]:
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
            return crawler, store

    crawler, store = asyncio.run(_run())
    report = crawler.report.as_dict()
    table = Table(title="Crawl report", header_style="bold magenta")
    for k, v in report.items():
        table.add_row(k, str(v))
    console.print(table)
    console.print(f"Results stored in [bold]{db}[/bold] — explore with:")
    console.print(
        f'  sqlite3 "{db}" "SELECT url, title FROM pages ORDER BY text_len DESC LIMIT 20;"'
    )


if __name__ == "__main__":
    app()
