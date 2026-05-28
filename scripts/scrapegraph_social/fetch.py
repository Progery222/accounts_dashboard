"""Загрузка HTML через Playwright (как FetchNode ScrapeGraph)."""

from __future__ import annotations


def fetch_page_html(url: str, *, headless: bool = True, timeout_ms: int = 120_000) -> str:
    from scrapegraphai.docloaders import ChromiumLoader

    loader = ChromiumLoader([url], headless=headless, timeout=timeout_ms)
    docs = loader.load()
    if not docs or not (docs[0].page_content or "").strip():
        raise ValueError("ChromiumLoader вернул пустой HTML")
    return docs[0].page_content
