#!/usr/bin/env python3
"""
Запасной путь ScrapeGraph (без cookies, без Django).

Пайплайн:
  1) Playwright Fetch (как ScrapeGraph FetchNode)
  2) Детерминированный разбор встроенного JSON (как platforms/*)
  3) При нехватке данных — SmartScraperGraph с html_mode=True на компактном JSON

Установка: см. scripts/requirements-scrapegraph-probe.txt + Ollama или OPENAI_API_KEY.

Примеры:
  .venv-scrapegraph\\Scripts\\python.exe scripts\\scrapegraph_social_probe.py --url https://www.youtube.com/@DebtCeilingDiaries
  .venv-scrapegraph\\Scripts\\python.exe scripts\\scrapegraph_social_probe.py --url https://www.instagram.com/thecapitolverdict/reels/ --llm-provider ollama
  .venv-scrapegraph\\Scripts\\python.exe scripts\\scrapegraph_social_probe.py --deterministic-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_ROOT = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from scrapegraph_social.extract import (  # noqa: E402
    compact_llm_context,
    detect_platform,
    extract_deterministic,
    is_sufficient,
)
from scrapegraph_social.fetch import fetch_page_html  # noqa: E402
from scrapegraph_social.llm_graph import (  # noqa: E402
    merge_deterministic_and_llm,
    run_on_context,
)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for name in (".env", "backend/.env", "backend/config/.env"):
        p = _ROOT / name
        if p.is_file():
            load_dotenv(p)


def _summarize(data: dict) -> None:
    posts = data.get("_posts") or data.get("posts") or []
    print("\n--- Сводка (формат близкий к dashboard _apply_refresh) ---")
    print(f"Платформа:      {data.get('platform', '—')}")
    print(f"Метод:          {data.get('_extraction', '—')}")
    print(f"Подписчики:     {data.get('follower_count', '—')}")
    print(f"Постов:         {data.get('post_count', len(posts))}")
    print(f"В _posts:       {len(posts)}")
    notes = (data.get("notes") or "").strip()
    if notes:
        print(f"Заметки:        {notes}")
    for i, p in enumerate(posts[:25], 1):
        if not isinstance(p, dict):
            continue
        print(
            f"  {i}. id={p.get('external_id', '')} views={p.get('view_count', 0)} "
            f"likes={p.get('like_count', 0)} url={p.get('post_url', '')}"
        )
    if len(posts) > 25:
        print(f"  … ещё {len(posts) - 25}")


def run_pipeline(
    *,
    url: str,
    headless: bool,
    llm_provider: str,
    model: str,
    html_mode: bool,
    deterministic_only: bool,
    no_llm: bool,
    save_html: str,
) -> dict:
    print(f"1/3 Fetch HTML ({'headless' if headless else 'headed'})…")
    html = fetch_page_html(url, headless=headless)
    if save_html:
        Path(save_html).write_text(html, encoding="utf-8", errors="replace")
        print(f"   HTML сохранён: {Path(save_html).resolve()}")

    print("2/3 Детерминированное извлечение (embedded JSON / RSS)…")
    det = extract_deterministic(url, html)
    det["platform"] = det.get("platform") or detect_platform(url)

    if is_sufficient(det):
        det["_extraction"] = "deterministic"
        print("   Достаточно данных без LLM.")
        return det

    if deterministic_only or no_llm:
        det["_extraction"] = "deterministic_partial"
        det["notes"] = (det.get("notes") or "") + " LLM отключён; данных мало."
        return det

    print(f"3/3 SmartScraperGraph html_mode={html_mode} ({llm_provider})…")
    ctx = compact_llm_context(url, html, det)
    print(f"   Контекст для LLM: {len(ctx)} символов")
    llm_out = run_on_context(
        ctx,
        headless=headless,
        llm_provider=llm_provider,
        model=model,
        html_mode=html_mode,
    )
    return merge_deterministic_and_llm(det, llm_out)


def main() -> int:
    parser = argparse.ArgumentParser(description="ScrapeGraph backup path (no cookies)")
    parser.add_argument(
        "--url",
        default="https://www.youtube.com/@DebtCeilingDiaries",
        help="URL профиля / reels / канала",
    )
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--llm-provider", choices=("openai", "ollama"), default="ollama")
    parser.add_argument("--model", default="")
    parser.add_argument(
        "--html-mode",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="SmartScraperGraph: пропуск Html2Text ParseNode (по умолчанию True)",
    )
    parser.add_argument(
        "--deterministic-only",
        action="store_true",
        help="Только шаг 2 (без LLM)",
    )
    parser.add_argument("--no-llm", action="store_true", help="Синоним --deterministic-only")
    parser.add_argument("--out", default="", help="JSON результат")
    parser.add_argument("--save-html", default="", help="Сохранить сырой HTML")
    args = parser.parse_args()

    _load_dotenv()
    os.environ.setdefault("SCRAPEGRAPHAI_TELEMETRY_ENABLED", "false")

    url = args.url.strip()
    print(f"URL: {url}\n")

    try:
        data = run_pipeline(
            url=url,
            headless=not args.no_headless,
            llm_provider=args.llm_provider,
            model=args.model.strip(),
            html_mode=args.html_mode,
            deterministic_only=args.deterministic_only,
            no_llm=args.no_llm,
            save_html=args.save_html,
        )
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(data, ensure_ascii=False, indent=2)
    print(text)
    _summarize(data)

    if args.out:
        p = Path(args.out)
        p.write_text(text + "\n", encoding="utf-8")
        print(f"\nСохранено: {p.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
