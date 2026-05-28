#!/usr/bin/env python3
"""
Диагностика пайплайна ScrapeGraphAI на YouTube (без LLM).
Сохраняет артефакты в scripts/scrapegraph_debug/.

  .venv-scrapegraph\\Scripts\\python.exe scripts\\scrapegraph_youtube_diagnostic.py
  .venv-scrapegraph\\Scripts\\python.exe scripts\\scrapegraph_youtube_diagnostic.py --url https://www.youtube.com/@DebtCeilingDiaries
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

URL_DEFAULT = "https://www.youtube.com/@DebtCeilingDiaries"
OUT_DIR = Path(__file__).resolve().parent / "scrapegraph_debug"
CHUNK_SIZE = 8192 - 250  # как SmartScraperGraph + ParseNode для model_tokens=8192


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=URL_DEFAULT)
    args = parser.parse_args()
    url = args.url.strip()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^\w.-]+", "_", url.split("/")[-1] or "page")[:60]
    report: dict = {"url": url, "steps": {}}

    # ── 0) httpx (как dashboard) ─────────────────────────────────────────
    import httpx

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    r = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
    httpx_html = r.text
    (OUT_DIR / f"{slug}_00_httpx.html").write_text(httpx_html, encoding="utf-8", errors="replace")
    report["steps"]["httpx"] = {
        "status": r.status_code,
        "bytes": len(httpx_html),
        "ytInitialData": "ytInitialData" in httpx_html,
        "og_title": _meta(httpx_html, "og:title"),
    }

    # ── 1) ChromiumLoader (как FetchNode ScrapeGraph) ─────────────────────
    from scrapegraphai.docloaders import ChromiumLoader

    loader = ChromiumLoader([url], headless=True, timeout=120000)
    docs = loader.load()
    raw_html = docs[0].page_content if docs else ""
    (OUT_DIR / f"{slug}_01_chromium_raw.html").write_text(
        raw_html, encoding="utf-8", errors="replace"
    )
    report["steps"]["chromium_loader"] = {
        "bytes": len(raw_html),
        "ytInitialData": "ytInitialData" in raw_html,
        "log_in_literal": "Log in to continue" in raw_html,
        "sign_in_literal": "sign in" in raw_html.lower()[:100_000],
    }

    # ── 2) Html2Text (как ParseNode parse_html=True) ─────────────────────
    from langchain_community.document_transformers import Html2TextTransformer
    from langchain_core.documents import Document

    doc_in = [Document(page_content=raw_html, metadata={"source": url})]
    doc_out = Html2TextTransformer(ignore_links=False).transform_documents(doc_in)[0]
    md_text = doc_out.page_content or ""
    (OUT_DIR / f"{slug}_02_html2text.md").write_text(md_text, encoding="utf-8", errors="replace")
    report["steps"]["html2text"] = {
        "chars": len(md_text),
        "lines": md_text.count("\n"),
        "preview": md_text[:400].replace("\n", " "),
    }

    # ── 3) semchunk (как ParseNode → split_text_into_chunks) ─────────────
    from scrapegraphai.utils.split_text_into_chunks import split_text_into_chunks

    chunks = split_text_into_chunks(text=md_text, chunk_size=CHUNK_SIZE)
    report["steps"]["semchunk"] = {
        "chunk_size_config": CHUNK_SIZE,
        "num_chunks": len(chunks),
        "chunk_lengths": [len(c) for c in chunks[:20]],
    }
    for i, ch in enumerate(chunks[:5]):
        (OUT_DIR / f"{slug}_03_chunk_{i:02d}.txt").write_text(ch, encoding="utf-8", errors="replace")

    # ── 4) ytInitialData из сырого HTML ───────────────────────────────────
    m = re.search(r"var ytInitialData\s*=\s*(\{.+?\});\s*</script>", raw_html, re.DOTALL)
    if not m:
        m = re.search(r"ytInitialData\s*=\s*(\{.+?\});\s*</script>", raw_html, re.DOTALL)
    if m:
        blob = m.group(1)
        (OUT_DIR / f"{slug}_04_ytInitialData_snippet.json").write_text(
            blob[:500_000], encoding="utf-8", errors="replace"
        )
        report["steps"]["ytInitialData"] = {
            "found": True,
            "json_chars": len(blob),
            "videoId_count": len(re.findall(r'"videoId":"([^"]+)"', blob[:2_000_000])),
        }
    else:
        report["steps"]["ytInitialData"] = {"found": False}

    # ── отчёт ─────────────────────────────────────────────────────────────
    report_path = OUT_DIR / f"{slug}_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nАртефакты: {OUT_DIR.resolve()}")
    return 0


def _meta(html: str, prop: str) -> str:
    m = re.search(rf'<meta property="{re.escape(prop)}" content="([^"]*)"', html)
    return m.group(1) if m else ""


if __name__ == "__main__":
    raise SystemExit(main())
